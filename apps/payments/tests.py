"""
Subscription, payment and webhook tests.

Razorpay itself is never called: order creation and payment-signature checks
are patched, while webhook signatures are computed for real with the test
secret so the receiver's own verification path is exercised.
"""

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.payments.models import PaymentTransaction, Plan, Subscription, WebhookEvent
from apps.payments.services import FeatureGateService, PaymentService, SubscriptionService

pytestmark = pytest.mark.django_db

ORDER_ID = "order_TEST123"
PAYMENT_ID = "pay_TEST123"


@pytest.fixture
def business_plan(plans):
    return Plan.objects.create(
        name="Business Monthly",
        slug="business_monthly",
        tier=Plan.Tier.BUSINESS,
        billing_period=Plan.BillingPeriod.MONTHLY,
        price_inr=Decimal("2999"),
        max_active_jobs=None,
        max_team_members=5,
        has_candidate_search=True,
        sort_order=3,
    )


@pytest.fixture
def fake_razorpay():
    """Stand in for a successful order + a valid payment signature."""
    with (
        patch(
            "apps.payments.services.RazorpayClient.create_order",
            return_value={"id": ORDER_ID, "amount": 49900, "currency": "INR"},
        ) as order,
        patch(
            "apps.payments.services.RazorpayClient.verify_payment_signature",
            return_value=True,
        ) as signature,
    ):
        yield {"create_order": order, "verify_signature": signature}


def _pay(user, plan_slug="pro_monthly"):
    """Run the full create-order then verify flow."""
    PaymentService.create_order(user, plan_slug)
    return PaymentService.verify_and_activate(
        user=user,
        order_id=ORDER_ID,
        payment_id=PAYMENT_ID,
        signature="sig",
        plan_slug=plan_slug,
    )


# --------------------------------------------------------------------------
# Free trial
# --------------------------------------------------------------------------


def test_signup_grants_a_trial(seeker_user):
    sub = seeker_user.subscriptions.get()
    assert sub.status == Subscription.Status.TRIALING
    assert sub.plan.slug == "pro_monthly"
    assert sub.is_currently_active()


def test_trial_is_granted_only_once(seeker_user):
    assert SubscriptionService.grant_free_trial(seeker_user) is None
    assert seeker_user.subscriptions.count() == 1


def test_expired_trial_falls_back_to_the_free_plan(free_seeker):
    assert FeatureGateService.get_user_plan(free_seeker.user).slug == "free"
    assert SubscriptionService.get_active_subscription(free_seeker.user) is None


# --------------------------------------------------------------------------
# Order creation
# --------------------------------------------------------------------------


def test_create_order_records_a_transaction(free_seeker, fake_razorpay):
    result = PaymentService.create_order(free_seeker.user, "pro_monthly")

    txn = PaymentTransaction.objects.get(razorpay_order_id=ORDER_ID)
    assert result["order_id"] == ORDER_ID
    assert txn.status == PaymentTransaction.Status.CREATED
    assert txn.amount_inr == Decimal("499")


def test_cannot_buy_the_free_plan(free_seeker, fake_razorpay):
    with pytest.raises(ValidationError):
        PaymentService.create_order(free_seeker.user, "free")


def test_seeker_cannot_buy_a_recruiter_plan(free_seeker, business_plan, fake_razorpay):
    with pytest.raises(ValidationError):
        PaymentService.create_order(free_seeker.user, "business_monthly")


def test_recruiter_cannot_buy_a_seeker_plan(recruiter_user, fake_razorpay):
    with pytest.raises(ValidationError):
        PaymentService.create_order(recruiter_user, "pro_monthly")


def test_failed_order_creation_marks_the_transaction(free_seeker):
    with patch(
        "apps.payments.services.RazorpayClient.create_order",
        side_effect=RuntimeError("gateway down"),
    ):
        with pytest.raises(ValidationError):
            PaymentService.create_order(free_seeker.user, "pro_monthly")

    txn = PaymentTransaction.objects.latest("created_at")
    assert txn.status == PaymentTransaction.Status.FAILED
    assert "gateway down" in txn.failure_reason


# --------------------------------------------------------------------------
# Payment verification
# --------------------------------------------------------------------------


def test_successful_payment_activates_the_subscription(free_seeker, fake_razorpay):
    sub = _pay(free_seeker.user)

    assert sub.status == Subscription.Status.ACTIVE
    assert sub.plan.slug == "pro_monthly"
    assert sub.is_currently_active()
    assert FeatureGateService.get_user_plan(free_seeker.user).slug == "pro_monthly"


def test_verification_is_idempotent(free_seeker, fake_razorpay):
    """Replaying the same payment id must not create a second subscription."""
    first = _pay(free_seeker.user)
    second = PaymentService.verify_and_activate(
        user=free_seeker.user,
        order_id=ORDER_ID,
        payment_id=PAYMENT_ID,
        signature="sig",
        plan_slug="pro_monthly",
    )

    assert first.pk == second.pk
    assert PaymentTransaction.objects.filter(status=PaymentTransaction.Status.SUCCESS).count() == 1


def test_bad_signature_is_rejected_and_recorded(free_seeker, fake_razorpay):
    PaymentService.create_order(free_seeker.user, "pro_monthly")

    with patch(
        "apps.payments.services.RazorpayClient.verify_payment_signature",
        side_effect=RuntimeError("signature mismatch"),
    ):
        with pytest.raises(ValidationError):
            PaymentService.verify_and_activate(
                user=free_seeker.user,
                order_id=ORDER_ID,
                payment_id=PAYMENT_ID,
                signature="forged",
                plan_slug="pro_monthly",
            )

    txn = PaymentTransaction.objects.get(razorpay_order_id=ORDER_ID)
    assert txn.status == PaymentTransaction.Status.FAILED
    assert not Subscription.objects.filter(
        user=free_seeker.user, status=Subscription.Status.ACTIVE
    ).exists()


def test_unknown_order_is_rejected(free_seeker, fake_razorpay):
    with pytest.raises(ValidationError):
        PaymentService.verify_and_activate(
            user=free_seeker.user,
            order_id="order_NOPE",
            payment_id=PAYMENT_ID,
            signature="sig",
            plan_slug="pro_monthly",
        )


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


def test_renewing_the_same_tier_extends_the_period(free_seeker, fake_razorpay):
    first = _pay(free_seeker.user)
    original_end = first.current_period_end

    PaymentService.create_order(free_seeker.user, "pro_monthly")
    second = PaymentService.verify_and_activate(
        user=free_seeker.user,
        order_id=ORDER_ID,
        payment_id="pay_SECOND",
        signature="sig",
        plan_slug="pro_monthly",
    )

    assert second.pk == first.pk, "renewal reuses the same subscription"
    assert second.current_period_end > original_end


def test_cancelling_a_trial_ends_access_immediately(seeker_user):
    sub, access_end = SubscriptionService.cancel_subscription(
        seeker_user,
        reason="not needed",
    )

    assert sub.status == Subscription.Status.CANCELLED
    assert sub.auto_renew is False
    assert not sub.is_currently_active()


def test_cancelling_a_paid_plan_keeps_access_until_period_end(free_seeker, fake_razorpay):
    paid = _pay(free_seeker.user)

    sub, access_end = SubscriptionService.cancel_subscription(free_seeker.user)

    assert sub.cancelled_at is not None
    assert sub.auto_renew is False
    assert access_end == paid.current_period_end
    assert sub.is_currently_active(), "paid access survives cancellation"


def test_cancelling_without_a_subscription_is_rejected(free_seeker):
    with pytest.raises(ValidationError):
        SubscriptionService.cancel_subscription(free_seeker.user)


def test_expiry_sweep_marks_ended_subscriptions(seeker_user):
    sub = seeker_user.subscriptions.get()
    sub.trial_ends_at = timezone.now() - timedelta(days=1)
    sub.save()

    assert SubscriptionService.expire_ended_subscriptions() >= 1

    sub.refresh_from_db()
    assert sub.status == Subscription.Status.EXPIRED


# --------------------------------------------------------------------------
# Webhooks
# --------------------------------------------------------------------------


def _signed_post(client, payload, event_id="evt_TEST1", secret=None):
    body = json.dumps(payload)
    secret = secret or settings.RAZORPAY_WEBHOOK_SECRET
    signature = hmac.new(
        secret.encode(),
        body.encode(),
        hashlib.sha256,
    ).hexdigest()

    return client.post(
        "/api/v1/webhooks/razorpay/",
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=signature,
        HTTP_X_RAZORPAY_EVENT_ID=event_id,
    )


def _captured_payload(amount_paise=49900):
    return {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": PAYMENT_ID,
                    "order_id": ORDER_ID,
                    "amount": amount_paise,
                }
            }
        },
    }


def test_webhook_without_a_signature_is_rejected(client):
    response = client.post(
        "/api/v1/webhooks/razorpay/",
        data=json.dumps(_captured_payload()),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert not WebhookEvent.objects.exists()


def test_webhook_with_a_forged_signature_is_rejected(client):
    response = _signed_post(client, _captured_payload(), secret="wrong_secret")

    assert response.status_code == 400
    assert not WebhookEvent.objects.exists()


def test_captured_webhook_activates_the_subscription(client, free_seeker, fake_razorpay):
    PaymentService.create_order(free_seeker.user, "pro_monthly")

    response = _signed_post(client, _captured_payload())

    assert response.status_code == 200
    txn = PaymentTransaction.objects.get(razorpay_order_id=ORDER_ID)
    assert txn.status == PaymentTransaction.Status.SUCCESS
    assert Subscription.objects.filter(
        user=free_seeker.user, status=Subscription.Status.ACTIVE
    ).exists()


@pytest.mark.regression
def test_duplicate_webhook_is_not_processed_twice(client, free_seeker, fake_razorpay):
    """
    Blueprint edge case: "What happens when a Razorpay webhook arrives twice?"
    The event id is unique and an already-PROCESSED event short-circuits, so
    the second delivery must not extend the period a second time.
    """
    PaymentService.create_order(free_seeker.user, "pro_monthly")

    _signed_post(client, _captured_payload())
    first_end = Subscription.objects.get(
        user=free_seeker.user,
        status=Subscription.Status.ACTIVE,
    ).current_period_end

    response = _signed_post(client, _captured_payload())

    assert response.status_code == 200
    assert WebhookEvent.objects.count() == 1
    assert (
        Subscription.objects.get(
            user=free_seeker.user,
            status=Subscription.Status.ACTIVE,
        ).current_period_end
        == first_end
    )


def test_amount_mismatch_does_not_activate(client, free_seeker, fake_razorpay):
    """A payment for the wrong amount must never unlock a plan."""
    PaymentService.create_order(free_seeker.user, "pro_monthly")

    response = _signed_post(client, _captured_payload(amount_paise=100))

    assert response.status_code == 200, "valid signature still returns 200"
    event = WebhookEvent.objects.get()
    assert event.processing_status == WebhookEvent.ProcessingStatus.FAILED
    assert not Subscription.objects.filter(
        user=free_seeker.user, status=Subscription.Status.ACTIVE
    ).exists()


def test_failed_payment_webhook_marks_the_transaction(client, free_seeker, fake_razorpay):
    PaymentService.create_order(free_seeker.user, "pro_monthly")

    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": PAYMENT_ID,
                    "order_id": ORDER_ID,
                    "error_description": "insufficient funds",
                }
            }
        },
    }
    _signed_post(client, payload, event_id="evt_FAIL")

    txn = PaymentTransaction.objects.get(razorpay_order_id=ORDER_ID)
    assert txn.status == PaymentTransaction.Status.FAILED
    assert "insufficient funds" in txn.failure_reason


def test_unknown_event_type_is_stored_but_ignored(client):
    _signed_post(client, {"event": "refund.created", "payload": {}}, event_id="evt_UNKNOWN")

    event = WebhookEvent.objects.get()
    assert event.processing_status == WebhookEvent.ProcessingStatus.PROCESSED


# --------------------------------------------------------------------------
# Feature gating
# --------------------------------------------------------------------------


def test_free_plan_quotas(free_seeker):
    usage = FeatureGateService.can_apply_to_job(free_seeker.user)
    assert usage["limit"] == 5
    assert FeatureGateService.has_feature(free_seeker.user, "resume_ai_analysis") is False


def test_paid_plan_unlocks_features(free_seeker, fake_razorpay):
    _pay(free_seeker.user)

    assert FeatureGateService.has_feature(free_seeker.user, "match_score")
    assert FeatureGateService.can_apply_to_job(free_seeker.user)["limit"] is None


def test_capabilities_snapshot_shape(free_seeker):
    caps = FeatureGateService.get_capabilities(free_seeker.user)

    assert caps["plan"]["slug"] == "free"
    assert "applications_per_month" in caps["limits"]
    assert "match_score" in caps["features"]
    assert caps["usage"]["applications"]["limit"] == 5


def test_unknown_feature_name_is_false(free_seeker):
    assert FeatureGateService.has_feature(free_seeker.user, "time_travel") is False


# --------------------------------------------------------------------------
# Refunds
# --------------------------------------------------------------------------


@pytest.fixture
def refundable(free_seeker, fake_razorpay):
    """A settled Pro payment, ready to be refunded."""
    _pay(free_seeker.user)
    return PaymentTransaction.objects.get(razorpay_payment_id=PAYMENT_ID)


@pytest.fixture
def fake_refund():
    with patch(
        "apps.payments.services.RazorpayClient.refund_payment",
        return_value={"id": "rfnd_TEST1", "status": "pending"},
    ) as m:
        yield m


@pytest.fixture
def admin_user(plans):
    from apps.accounts.models import User

    return User.objects.create_superuser(
        email="ops@test.com",
        password="TestPass123!",
    )


@pytest.mark.regression
def test_full_refund_is_recorded(refundable, fake_refund, admin_user):
    """
    Regression: the blueprint asks for admin-triggered refunds in both
    Feature 08 and Feature 10, but only the REFUNDED enum value existed -
    no model, no service, no admin action.
    """
    from apps.payments.models import Refund
    from apps.payments.services import RefundService

    refund = RefundService.issue(
        refundable,
        reason="Duplicate charge",
        actor=admin_user,
    )

    assert refund.amount_inr == Decimal("499")
    assert refund.status == Refund.Status.PENDING
    assert refund.razorpay_refund_id == "rfnd_TEST1"
    assert refund.issued_by == admin_user
    assert refund.reason == "Duplicate charge"

    refundable.refresh_from_db()
    assert refundable.status == PaymentTransaction.Status.REFUNDED


def test_full_refund_revokes_access(refundable, fake_refund, admin_user, free_seeker):
    from apps.payments.services import RefundService

    RefundService.issue(refundable, reason="Chargeback", actor=admin_user)

    assert FeatureGateService.get_user_plan(free_seeker.user).slug == "free"
    assert SubscriptionService.get_active_subscription(free_seeker.user) is None


def test_partial_refund_keeps_access(refundable, fake_refund, admin_user, free_seeker):
    """Half the money back should not mean all the access gone."""
    from apps.payments.services import RefundService

    refund = RefundService.issue(
        refundable,
        reason="Goodwill",
        amount_inr=200,
        actor=admin_user,
    )

    assert refund.access_revoked is False
    refundable.refresh_from_db()
    assert refundable.status == PaymentTransaction.Status.SUCCESS
    assert FeatureGateService.get_user_plan(free_seeker.user).slug == "pro_monthly"


def test_partial_refunds_accumulate(refundable, fake_refund, admin_user):
    from apps.payments.services import RefundService

    RefundService.issue(refundable, reason="First", amount_inr=200, actor=admin_user)
    assert RefundService.refundable_amount(refundable) == Decimal("299")

    RefundService.issue(refundable, reason="Second", amount_inr=299, actor=admin_user)
    assert RefundService.refundable_amount(refundable) == Decimal("0")

    refundable.refresh_from_db()
    assert refundable.status == PaymentTransaction.Status.REFUNDED


def test_cannot_refund_more_than_was_paid(refundable, fake_refund, admin_user):
    from apps.payments.services import RefundService

    with pytest.raises(ValidationError):
        RefundService.issue(refundable, reason="Too much", amount_inr=1000, actor=admin_user)


def test_cannot_refund_twice_in_full(refundable, fake_refund, admin_user):
    from apps.payments.services import RefundService

    RefundService.issue(refundable, reason="First", actor=admin_user)

    with pytest.raises(ValidationError):
        RefundService.issue(refundable, reason="Again", actor=admin_user)


def test_cannot_refund_an_unpaid_transaction(free_seeker, fake_razorpay, fake_refund, admin_user):
    from apps.payments.services import RefundService

    PaymentService.create_order(free_seeker.user, "pro_monthly")
    pending = PaymentTransaction.objects.get(razorpay_order_id=ORDER_ID)

    with pytest.raises(ValidationError):
        RefundService.issue(pending, reason="Nope", actor=admin_user)


def test_reason_is_required(refundable, fake_refund, admin_user):
    """The reason is the accountability record - an empty one is useless."""
    from apps.payments.services import RefundService

    with pytest.raises(ValidationError):
        RefundService.issue(refundable, reason="   ", actor=admin_user)


def test_gateway_failure_is_recorded_and_keeps_access(refundable, admin_user, free_seeker):
    from apps.payments.models import Refund
    from apps.payments.services import RefundService

    with patch(
        "apps.payments.services.RazorpayClient.refund_payment",
        side_effect=RuntimeError("refund declined"),
    ):
        with pytest.raises(ValidationError):
            RefundService.issue(refundable, reason="Try", actor=admin_user)

    refund = Refund.objects.get()
    assert refund.status == Refund.Status.FAILED
    assert "refund declined" in refund.failure_reason

    refundable.refresh_from_db()
    assert refundable.status == PaymentTransaction.Status.SUCCESS
    assert FeatureGateService.get_user_plan(free_seeker.user).slug == "pro_monthly"


def test_failed_refunds_do_not_consume_the_balance(refundable, admin_user):
    from apps.payments.services import RefundService

    with patch(
        "apps.payments.services.RazorpayClient.refund_payment",
        side_effect=RuntimeError("declined"),
    ):
        with pytest.raises(ValidationError):
            RefundService.issue(refundable, reason="Try", actor=admin_user)

    assert RefundService.refundable_amount(refundable) == Decimal("499")


def test_refund_webhook_marks_it_processed(client, refundable, fake_refund, admin_user):
    from apps.payments.models import Refund
    from apps.payments.services import RefundService

    refund = RefundService.issue(refundable, reason="Duplicate", actor=admin_user)
    assert refund.status == Refund.Status.PENDING

    _signed_post(
        client,
        {
            "event": "refund.processed",
            "payload": {"refund": {"entity": {"id": "rfnd_TEST1"}}},
        },
        event_id="evt_REFUND",
    )

    refund.refresh_from_db()
    assert refund.status == Refund.Status.PROCESSED


def test_refund_webhook_for_an_unknown_id_is_ignored(client):
    _signed_post(
        client,
        {
            "event": "refund.processed",
            "payload": {"refund": {"entity": {"id": "rfnd_GHOST"}}},
        },
        event_id="evt_GHOST",
    )

    event = WebhookEvent.objects.get()
    assert event.processing_status == WebhookEvent.ProcessingStatus.PROCESSED


# --------------------------------------------------------------------------
# Invoices
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_invoice_renders_as_a_pdf(refundable):
    """
    Regression: invoice.py returned a dict and said a later phase could turn
    it into a PDF and email it. Feature 08 asks for "auto invoice generation
    with email delivery" - neither the PDF nor the attachment existed.
    """
    from apps.payments.invoice_pdf import render_invoice_pdf

    pdf = render_invoice_pdf(refundable)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_invoice_filename_uses_the_invoice_number(refundable):
    from apps.payments.invoice import generate_invoice_data
    from apps.payments.invoice_pdf import invoice_filename

    number = generate_invoice_data(refundable)["invoice_number"]

    assert invoice_filename(refundable) == f"invoice-{number}.pdf"


def test_no_invoice_for_an_unpaid_transaction(free_seeker, fake_razorpay):
    from apps.payments.invoice_pdf import render_invoice_pdf

    PaymentService.create_order(free_seeker.user, "pro_monthly")
    pending = PaymentTransaction.objects.get(razorpay_order_id=ORDER_ID)

    with pytest.raises(ValueError):
        render_invoice_pdf(pending)


def test_gst_is_backed_out_of_the_paid_amount(refundable):
    """The paid amount is GST-inclusive, so subtotal + GST must equal it."""
    from decimal import Decimal

    from apps.payments.invoice import generate_invoice_data

    data = generate_invoice_data(refundable)
    total = Decimal(data["subtotal"]) + Decimal(data["gst"])

    assert total == Decimal(data["total"])


def test_a_user_can_download_their_own_invoice(refundable, free_seeker):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=free_seeker.user)

    response = client.get(f"/api/v1/payments/me/{refundable.id}/invoice/pdf/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "attachment;" in response["Content-Disposition"]


def test_a_user_cannot_download_someone_elses_invoice(refundable, plans):
    from rest_framework.test import APIClient

    from apps.accounts.models import User

    stranger = User.objects.create_user(
        email="nosy@test.com",
        password="TestPass123!",
        role=User.Role.SEEKER,
        is_email_verified=True,
    )
    client = APIClient()
    client.force_authenticate(user=stranger)

    response = client.get(f"/api/v1/payments/me/{refundable.id}/invoice/pdf/")

    assert response.status_code == 404


def test_payment_email_carries_the_invoice(
    free_seeker, fake_razorpay, django_capture_on_commit_callbacks
):
    """
    The blueprint's "email delivery" half of the requirement.

    The email is queued through transaction.on_commit, which never fires
    inside a test's rolled-back transaction, so the callbacks have to be
    captured and run explicitly.
    """
    from django.core import mail

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        _pay(free_seeker.user)

    assert len(mail.outbox) == 1
    attachments = mail.outbox[0].attachments
    assert len(attachments) == 1

    filename, content, mimetype = attachments[0]
    assert filename.endswith(".pdf")
    assert mimetype == "application/pdf"
    assert content.startswith(b"%PDF")


def test_a_broken_invoice_does_not_block_the_email(
    free_seeker,
    fake_razorpay,
    django_capture_on_commit_callbacks,
):
    """
    The money has already moved by this point. A PDF problem must never stop
    the customer being told their payment went through.
    """
    from unittest.mock import patch

    from django.core import mail

    mail.outbox = []
    with patch(
        "apps.payments.invoice_pdf.render_invoice_pdf",
        side_effect=RuntimeError("reportlab exploded"),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _pay(free_seeker.user)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].attachments == []


def test_customer_email_is_not_repeated_when_no_name_is_set(refundable):
    """
    The name falls back to the email, so the PDF used to print the same
    address twice under BILLED TO.
    """
    from apps.payments.invoice import generate_invoice_data

    refundable.user.full_name = ""
    refundable.user.save(update_fields=["full_name"])

    data = generate_invoice_data(refundable)

    assert data["customer"]["name"] == data["customer"]["email"]


def test_invoice_identity_comes_from_settings(refundable, settings):
    """A placeholder GSTIN must never be baked into the code."""
    from apps.payments.invoice import generate_invoice_data

    settings.INVOICE_COMPANY_NAME = "Test Co"
    settings.INVOICE_GSTIN = "29ABCDE1234F1Z5"

    company = generate_invoice_data(refundable)["company"]

    assert company["name"] == "Test Co"
    assert company["gstin"] == "29ABCDE1234F1Z5"


def test_gst_rate_is_configurable(refundable, settings):
    from decimal import Decimal

    from apps.payments.invoice import generate_invoice_data

    settings.INVOICE_GST_RATE = 5.0
    data = generate_invoice_data(refundable)

    # normalize() strips the trailing zero, so 5.0 renders as "5"
    assert data["gst_rate"] == "5"
    # Still adds up: a different rate must not break the arithmetic
    assert Decimal(data["subtotal"]) + Decimal(data["gst"]) == Decimal(data["total"])
