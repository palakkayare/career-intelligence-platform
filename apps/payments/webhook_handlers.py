"""
Event-specific handlers.
Router dispatches to appropriate function based on event type.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import PaymentTransaction, Subscription, WebhookEvent
from .services import SubscriptionService

logger = logging.getLogger(__name__)


def process_event(event: WebhookEvent):
    """
    Route event to appropriate handler based on event_type.
    """
    handlers = {
        "payment.captured": handle_payment_captured,
        "payment.failed": handle_payment_failed,
        "refund.processed": handle_refund_processed,
        "order.paid": handle_order_paid,
        "subscription.cancelled": handle_subscription_cancelled,
        "subscription.charged": handle_subscription_charged,
    }

    handler = handlers.get(event.event_type)
    if not handler:
        logger.info(f"No handler for event type: {event.event_type}")
        return

    handler(event)


# ─── Handlers ──────────────────────────────────────────────


@transaction.atomic
def handle_payment_captured(event: WebhookEvent):
    """
    Payment was successful and captured.
    This is the most reliable signal that payment is complete.
    """

    payload = event.payload
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})

    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")
    amount_paise = payment_entity.get("amount", 0)

    if not payment_id or not order_id:
        raise ValueError("Missing payment_id or order_id in payload")

    # Find our transaction
    txn = (
        PaymentTransaction.objects.select_for_update()
        .filter(
            razorpay_order_id=order_id,
        )
        .first()
    )

    if not txn:
        logger.warning(
            f"payment.captured for unknown order {order_id}. "
            "Possibly an order created outside our system."
        )
        return

    # Already processed via /verify endpoint? Idempotent.
    if txn.status == PaymentTransaction.Status.SUCCESS:
        logger.info(f"Transaction {txn.id} already success, webhook is confirming")
        return

    # Verify amount matches (extra safety)
    expected_amount = int(txn.amount_inr * 100)
    if amount_paise != expected_amount:
        raise ValueError(
            f"Amount mismatch: expected {expected_amount} paise, got {amount_paise} paise"
        )

    # Update transaction
    txn.razorpay_payment_id = payment_id
    txn.status = PaymentTransaction.Status.SUCCESS
    txn.save(update_fields=["razorpay_payment_id", "status"])

    # Activate subscription
    SubscriptionService.activate_paid_subscription(
        user=txn.user,
        plan=txn.plan,
        transaction_obj=txn,
    )

    logger.info(f"Subscription activated via webhook for {txn.user.email} (plan: {txn.plan.slug})")


@transaction.atomic
def handle_refund_processed(event: WebhookEvent):
    """
    refund.processed - the money has actually moved.

    Refunds are issued from the admin, which creates the Refund row as
    PENDING; this webhook is what confirms settlement at the gateway.
    """
    from .services import RefundService

    payload = event.payload
    entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
    refund_id = entity.get("id")

    if not refund_id:
        logger.warning("refund.processed with no refund id in payload")
        return

    refund = RefundService.mark_processed(refund_id)
    if refund is None:
        return

    logger.info(f"Refund {refund_id} confirmed processed")


def handle_payment_failed(event: WebhookEvent):
    """Payment failed. Mark transaction failed."""
    payload = event.payload
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})

    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")
    error_description = payment_entity.get("error_description", "")

    txn = PaymentTransaction.objects.filter(razorpay_order_id=order_id).first()

    if not txn:
        logger.warning(f"payment.failed for unknown order {order_id}")
        return

    # Don't override already-success transactions (rare race condition)
    if txn.status == PaymentTransaction.Status.SUCCESS:
        logger.warning(f"payment.failed received for already-success txn {txn.id}. Ignoring.")
        return

    txn.razorpay_payment_id = payment_id or ""
    txn.status = PaymentTransaction.Status.FAILED
    txn.failure_reason = error_description[:1000]
    txn.save(update_fields=["razorpay_payment_id", "status", "failure_reason"])

    logger.info(f"Transaction {txn.id} marked failed: {error_description}")


def handle_order_paid(event: WebhookEvent):
    """
    `order.paid` is similar to `payment.captured` but at the order level.
    For one-time orders (our Phase 1 flow), payment.captured is enough.
    Implement for completeness.
    """
    payload = event.payload
    order_entity = payload.get("payload", {}).get("order", {}).get("entity", {})

    if not order_entity:
        return

    order_id = order_entity.get("id")
    txn = PaymentTransaction.objects.filter(razorpay_order_id=order_id).first()

    if txn and txn.status == PaymentTransaction.Status.SUCCESS:
        logger.info(f"order.paid: order {order_id} already success")
        return

    logger.info(f"order.paid received for order {order_id}, payment.captured will handle it")


@transaction.atomic
def handle_subscription_cancelled(event: WebhookEvent):
    """
    Recurring subscription was cancelled.
    Phase 3+ — when we add Razorpay Subscriptions API for auto-renewal.
    For now, just log.
    """
    payload = event.payload
    sub_entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
    razorpay_sub_id = sub_entity.get("id")

    sub = Subscription.objects.filter(razorpay_subscription_id=razorpay_sub_id).first()

    if not sub:
        logger.info(
            f"subscription.cancelled for {razorpay_sub_id} — no matching DB record. "
            "Probably from Phase 3+ flow not yet implemented."
        )
        return

    sub.status = Subscription.Status.CANCELLED
    sub.cancelled_at = timezone.now()
    sub.cancellation_reason = sub_entity.get("reason", "Cancelled by Razorpay")
    sub.auto_renew = False
    sub.save()

    logger.info(f"Subscription {sub.id} cancelled via webhook")


@transaction.atomic
def handle_subscription_charged(event: WebhookEvent):
    """
    Recurring charge happened — extend the subscription period.
    Phase 3+ feature when we use Razorpay Subscriptions API.
    """
    payload = event.payload
    sub_entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    razorpay_sub_id = sub_entity.get("id")

    sub = Subscription.objects.filter(razorpay_subscription_id=razorpay_sub_id).first()

    if not sub:
        logger.info(f"subscription.charged for unknown {razorpay_sub_id}")
        return

    # Extend period
    days = sub.plan.period_days
    new_end = (sub.current_period_end or timezone.now()) + timedelta(days=days)

    sub.current_period_start = sub.current_period_end or timezone.now()
    sub.current_period_end = new_end
    sub.status = Subscription.Status.ACTIVE
    sub.save()

    # Record the renewal transaction
    PaymentTransaction.objects.create(
        subscription=sub,
        user=sub.user,
        plan=sub.plan,
        amount_inr=sub.plan.price_inr,
        status=PaymentTransaction.Status.SUCCESS,
        razorpay_order_id=sub_entity.get("current_order_id", ""),
        razorpay_payment_id=payment_entity.get("id", ""),
    )

    logger.info(f"Subscription {sub.id} renewed to {new_end}")
