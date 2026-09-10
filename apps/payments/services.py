"""
Business logic for subscriptions and payments.
"""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import PaymentTransaction, Plan, Refund, Subscription
from .razorpay_client import RazorpayClient

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Manages subscription lifecycle."""

    # Contact-reveal credits granted by each paid tier
    REVEAL_CREDITS_BY_TIER = {
        "business": 25,
    }

    @classmethod
    @transaction.atomic
    def grant_free_trial(cls, user):
        """
        Grant 7-day Pro trial on signup.
        Idempotent — won't create duplicate trial.
        """
        # Already has any subscription?
        if Subscription.objects.filter(user=user).exists():
            return None

        # Find appropriate Pro plan
        if user.role == "seeker":
            trial_plan = Plan.objects.filter(slug="pro_monthly").first()
        elif user.role == "recruiter":
            trial_plan = Plan.objects.filter(slug="business_monthly").first()
        else:
            return None  # Admins don't need trials

        if not trial_plan:
            return None

        now = timezone.now()
        trial_days = settings.FREE_TRIAL_DAYS

        return Subscription.objects.create(
            user=user,
            plan=trial_plan,
            status=Subscription.Status.TRIALING,
            trial_starts_at=now,
            trial_ends_at=now + timedelta(days=trial_days),
        )

    @classmethod
    def get_active_subscription(cls, user):
        """Get user's currently-active subscription (or None)."""
        sub = Subscription.objects.filter(user=user).order_by("-created_at").first()
        if sub and sub.is_currently_active():
            return sub
        return None

    @classmethod
    def has_pro_access(cls, user):
        """
        Check if user has Pro/Business access right now.
        Used by feature gating.
        """
        sub = cls.get_active_subscription(user)
        if not sub:
            return False
        return sub.plan.is_paid or sub.status == Subscription.Status.TRIALING

    @classmethod
    @transaction.atomic
    def activate_paid_subscription(cls, user, plan, transaction_obj):
        """
        Activate or extend a paid subscription after successful payment.

        Side effects, in order:
          1. Sync recruiter contact-reveal credits to the new plan.
          2. Convert a pending referral, if this user was referred.
        """
        now = timezone.now()

        # Existing subscription? Replace or extend.
        existing = Subscription.objects.filter(user=user).order_by("-created_at").first()

        if existing and existing.is_currently_active() and existing.plan.tier == plan.tier:
            # Same tier — extend the period
            base_time = max(existing.current_period_end or now, now)
            existing.plan = plan
            existing.status = Subscription.Status.ACTIVE
            existing.current_period_start = now
            existing.current_period_end = base_time + timedelta(days=plan.period_days)
            existing.cancelled_at = None
            existing.save()
            subscription = existing
        else:
            # New subscription (or different tier — supersedes existing)
            if existing:
                existing.status = Subscription.Status.EXPIRED
                existing.save(update_fields=["status"])

            subscription = Subscription.objects.create(
                user=user,
                plan=plan,
                status=Subscription.Status.ACTIVE,
                current_period_start=now,
                current_period_end=now + timedelta(days=plan.period_days),
            )

        # Link transaction to subscription
        transaction_obj.subscription = subscription
        transaction_obj.save(update_fields=["subscription"])

        # Grant contact-reveal credits for recruiter plans
        cls.sync_recruiter_credits(subscription)

        # Convert a pending referral, if this user has one.
        # Wrapped so referral logic can never roll back a successful payment.
        try:
            from apps.referrals.services import ReferralService

            ReferralService.trigger_conversion(user, transaction_obj)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).error(f"Referral conversion failed: {exc}")

        return subscription

    @classmethod
    @transaction.atomic
    def cancel_subscription(cls, user, reason=""):
        """
        Graceful cancellation:
        - TRIALING: cancel immediately (nothing was paid).
        - ACTIVE (paid): keep access until current_period_end; just turn
          off auto_renew. The expire_subscriptions command marks it
          EXPIRED once the period actually ends.
        Returns (subscription, access_end_datetime).
        """
        sub = cls.get_active_subscription(user)
        if not sub:
            raise ValidationError({"detail": "No active subscription to cancel."})

        sub.cancelled_at = timezone.now()
        sub.cancellation_reason = reason[:1000]
        sub.auto_renew = False

        if sub.status == Subscription.Status.TRIALING:
            # Trials end instantly — the user paid nothing
            sub.status = Subscription.Status.CANCELLED
            access_end = timezone.now()
        else:
            # Paid — status stays ACTIVE until the period ends
            access_end = sub.current_period_end

        sub.save()
        return sub, access_end

    @classmethod
    def expire_ended_subscriptions(cls):
        """
        Cron entrypoint: mark subscriptions whose period has ended
        as EXPIRED. Returns the number of rows updated.
        """
        now = timezone.now()

        # Collect before updating: a bulk update returns a count, not the
        # rows, and each affected user needs telling why their Pro features
        # stopped working.
        expiring = list(
            Subscription.objects.filter(
                Q(
                    status=Subscription.Status.TRIALING,
                    trial_ends_at__lt=now,
                )
                | Q(
                    status=Subscription.Status.ACTIVE,
                    current_period_end__lt=now,
                    auto_renew=False,
                )
            ).select_related("user", "plan")
        )

        if not expiring:
            return 0

        Subscription.objects.filter(
            pk__in=[s.pk for s in expiring],
        ).update(status=Subscription.Status.EXPIRED)

        from apps.notifications.triggers import notify_subscription_expired

        for subscription in expiring:
            try:
                notify_subscription_expired(subscription)
            except Exception:
                # One failed notification must not stop the sweep, and the
                # subscription is already correctly marked expired.
                logger.exception(
                    "Could not notify %s about expiry",
                    subscription.user_id,
                )

        return len(expiring)

    @classmethod
    def sync_recruiter_credits(cls, subscription):
        """
        Align RecruiterCredits.monthly_reveal_limit with the active plan.
        Called right after a subscription is activated or changed.
        """
        if subscription.user.role != "recruiter":
            return None

        recruiter = getattr(subscription.user, "recruiter_profile", None)
        if recruiter is None:
            return None

        plan = subscription.plan
        credits_limit = 0
        if plan.is_paid:
            credits_limit = cls.REVEAL_CREDITS_BY_TIER.get(plan.tier, 0)

        from apps.recruiters.models import RecruiterCredits

        credits, _ = RecruiterCredits.objects.get_or_create(
            recruiter=recruiter,
            defaults={"monthly_reveal_limit": credits_limit},
        )
        if credits.monthly_reveal_limit != credits_limit:
            credits.monthly_reveal_limit = credits_limit
            credits.save(update_fields=["monthly_reveal_limit"])

        return credits


class PaymentService:
    """Manages payment order creation and verification."""

    @classmethod
    def create_order(cls, user, plan_slug):
        """
        Create a Razorpay order for the given plan.
        Returns dict with order details for frontend.

        Deliberately NOT wrapped in transaction.atomic. Two reasons: the
        failure record below has to survive the ValidationError that follows
        it, and an atomic block would hold a database connection open for the
        whole round trip to Razorpay.
        """
        try:
            plan = Plan.objects.get(slug=plan_slug, is_active=True)
        except Plan.DoesNotExist:
            raise ValidationError({"plan_slug": "Invalid plan."})

        if not plan.is_paid:
            raise ValidationError({"plan_slug": "Cannot pay for free plan."})

        # Verify user role matches plan tier
        cls._validate_user_can_buy(user, plan)

        # Create internal transaction record FIRST
        # (helps trace even if Razorpay call fails)
        transaction_obj = PaymentTransaction.objects.create(
            user=user,
            plan=plan,
            amount_inr=plan.price_inr,
            status=PaymentTransaction.Status.CREATED,
            razorpay_order_id="",  # Set after Razorpay call
        )

        # Generate short receipt ID (Razorpay max 40 chars)
        receipt = f"txn_{transaction_obj.id}_{uuid.uuid4().hex[:8]}"

        try:
            order = RazorpayClient.create_order(
                amount_inr=plan.price_inr,
                receipt=receipt,
                notes={
                    "transaction_id": str(transaction_obj.id),
                    "user_id": str(user.id),
                    "plan_slug": plan.slug,
                },
            )
        except Exception as e:
            transaction_obj.status = PaymentTransaction.Status.FAILED
            transaction_obj.failure_reason = f"Razorpay order creation failed: {str(e)}"
            transaction_obj.save()
            raise ValidationError({"detail": "Could not create payment order. Please try again."})

        # Save Razorpay order_id
        transaction_obj.razorpay_order_id = order["id"]
        transaction_obj.save(update_fields=["razorpay_order_id"])

        return {
            "order_id": order["id"],
            "amount": order["amount"],  # paise
            "currency": order["currency"],
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
            "plan": {
                "slug": plan.slug,
                "name": plan.name,
                "price_inr": str(plan.price_inr),
            },
            "transaction_id": str(transaction_obj.id),
        }

    @classmethod
    def verify_and_activate(cls, user, order_id, payment_id, signature, plan_slug):
        """
        Verify the Razorpay payment signature, then activate the subscription.
        IDEMPOTENT - safe to call repeatedly with the same payment_id.

        The signature is checked before any write transaction opens. Doing it
        inside one meant the ValidationError rolled back the very row that
        recorded the failure, leaving no trace of rejected or forged payments.
        """
        # -- Idempotency check --
        existing = PaymentTransaction.objects.filter(
            razorpay_payment_id=payment_id,
            status=PaymentTransaction.Status.SUCCESS,
        ).first()
        if existing:
            # Already processed - return the same subscription
            return existing.subscription

        # -- Find the transaction we created earlier --
        try:
            txn = PaymentTransaction.objects.get(
                user=user,
                razorpay_order_id=order_id,
                status=PaymentTransaction.Status.CREATED,
            )
        except PaymentTransaction.DoesNotExist:
            raise ValidationError({"detail": "Order not found or already processed."})

        # -- Verify signature (CRITICAL) --
        try:
            RazorpayClient.verify_payment_signature(order_id, payment_id, signature)
        except Exception as e:
            txn.status = PaymentTransaction.Status.FAILED
            txn.failure_reason = f"Signature verification failed: {str(e)}"
            txn.razorpay_payment_id = payment_id
            txn.razorpay_signature = signature
            txn.save()
            raise ValidationError(
                {"detail": "Invalid payment signature. Possibly tampered request."}
            )

        return cls._mark_paid_and_activate(user, txn.pk, payment_id, signature, plan_slug)

    @classmethod
    @transaction.atomic
    def _mark_paid_and_activate(cls, user, txn_pk, payment_id, signature, plan_slug):
        """
        Success path only: flip the transaction to SUCCESS and switch the
        subscription on. Atomic, because a half-applied payment is far worse
        than a lost diagnostic row.
        """
        txn = PaymentTransaction.objects.select_for_update().get(pk=txn_pk)

        # Another request may have won the race while we verified
        if txn.status == PaymentTransaction.Status.SUCCESS:
            return txn.subscription

        txn.razorpay_payment_id = payment_id
        txn.razorpay_signature = signature
        txn.status = PaymentTransaction.Status.SUCCESS
        txn.save(
            update_fields=[
                "razorpay_payment_id",
                "razorpay_signature",
                "status",
            ]
        )

        plan = Plan.objects.get(slug=plan_slug)
        subscription = SubscriptionService.activate_paid_subscription(
            user=user,
            plan=plan,
            transaction_obj=txn,
        )

        # Notify the user that the payment succeeded
        from apps.notifications.triggers import notify_payment_success

        notify_payment_success(txn)

        return subscription

    @staticmethod
    def _validate_user_can_buy(user, plan):
        """Seekers can buy Pro, recruiters can buy Business."""
        if plan.tier == Plan.Tier.PRO and user.role != "seeker":
            raise ValidationError({"plan_slug": "Pro plans are for job seekers."})
        if plan.tier == Plan.Tier.BUSINESS and user.role != "recruiter":
            raise ValidationError({"plan_slug": "Business plans are for recruiters."})


class FeatureGateService:
    """
    Single source of truth for "what can this user do right now?"

    Every gating decision in the codebase should flow through here,
    so quotas and feature flags live on the Plan model (admin-editable)
    instead of being hardcoded anywhere.
    """

    @classmethod
    def get_user_plan(cls, user):
        """
        Return the Plan the user currently has access to.
        Falls back to the Free plan when there is no active subscription.
        """
        sub = SubscriptionService.get_active_subscription(user)
        if sub and sub.is_currently_active():
            return sub.plan

        # No active subscription — everyone defaults to the Free tier
        try:
            return Plan.objects.get(slug="free")
        except Plan.DoesNotExist:
            return None

    @classmethod
    def can_apply_to_job(cls, user):
        """
        Quota check for job applications.
        Returns a dict the frontend can render directly:
        {can, used, limit, remaining, plan} — limit None means unlimited.
        """
        plan = cls.get_user_plan(user)
        if not plan:
            return {"can": False, "reason": "No plan available"}

        used = cls._count_recent_applications(user)

        # Unlimited plans skip the arithmetic entirely
        if plan.max_applications_per_month is None:
            return {
                "can": True,
                "used": used,
                "limit": None,
                "remaining": None,
                "plan": plan.name,
            }

        remaining = max(0, plan.max_applications_per_month - used)
        return {
            "can": remaining > 0,
            "used": used,
            "limit": plan.max_applications_per_month,
            "remaining": remaining,
            "plan": plan.name,
        }

    @classmethod
    def can_post_job(cls, recruiter_profile):
        """
        Quota check for job postings. Draft and pending jobs count toward
        the limit too — otherwise a recruiter could stockpile drafts and
        submit them all at once.
        """
        plan = cls.get_user_plan(recruiter_profile.user)
        if not plan:
            return {"can": False, "reason": "No plan available"}

        if plan.max_active_jobs is None:
            return {"can": True, "limit": None, "plan": plan.name}

        from apps.jobs.models import Job

        active = Job.objects.filter(
            posted_by=recruiter_profile,
            status__in=[
                Job.Status.DRAFT,
                Job.Status.PENDING_APPROVAL,
                Job.Status.ACTIVE,
            ],
            is_deleted=False,
        ).count()

        remaining = max(0, plan.max_active_jobs - active)
        return {
            "can": remaining > 0,
            "active": active,
            "limit": plan.max_active_jobs,
            "remaining": remaining,
            "plan": plan.name,
        }

    @classmethod
    def applicants_view_limit(cls, recruiter_profile):
        """
        How many applicants the recruiter may view per job.
        Returns None for unlimited.
        """
        plan = cls.get_user_plan(recruiter_profile.user)
        if not plan:
            return 0
        return plan.max_applicants_view_per_job  # None = unlimited

    @classmethod
    def has_feature(cls, user, feature_name):
        """
        Boolean feature-flag check, e.g. has_feature(user, 'match_score').
        Maps to the Plan's has_<feature_name> field; unknown names are False.
        """
        plan = cls.get_user_plan(user)
        if not plan:
            return False
        return getattr(plan, f"has_{feature_name}", False)

    @classmethod
    def get_capabilities(cls, user):
        """
        Full snapshot of everything the user can do right now.
        The frontend fetches this once and renders the UI from it.
        """
        plan = cls.get_user_plan(user)
        if not plan:
            return {}

        capabilities = {
            "plan": {
                "name": plan.name,
                "slug": plan.slug,
                "tier": plan.tier,
            },
            "limits": {
                "applications_per_month": plan.max_applications_per_month,
                "active_jobs": plan.max_active_jobs,
                "applicants_view_per_job": plan.max_applicants_view_per_job,
                "resumes": plan.max_resumes,
                "team_members": plan.max_team_members,
                "saved_searches": plan.max_saved_searches,
            },
            "features": {
                "match_score": plan.has_match_score,
                "skill_gap": plan.has_skill_gap,
                "career_path": plan.has_career_path,
                "candidate_search": plan.has_candidate_search,
                "priority_search_visibility": plan.has_priority_search_visibility,
                "advanced_filters": plan.has_advanced_filters,
                "company_branding": plan.has_company_branding,
                "analytics_dashboard": plan.has_analytics_dashboard,
                "resume_ai_analysis": plan.has_resume_ai_analysis,
                "salary_insights": plan.has_salary_insights,
            },
        }

        # Attach live usage numbers for the role that has quotas
        if user.role == "seeker":
            capabilities["usage"] = {
                "applications": cls.can_apply_to_job(user),
            }
        elif user.role == "recruiter" and hasattr(user, "recruiter_profile"):
            capabilities["usage"] = {
                "jobs": cls.can_post_job(user.recruiter_profile),
            }

        return capabilities

    # ─── Helpers ───

    @staticmethod
    def _count_recent_applications(user):
        """
        Applications SUBMITTED in the rolling 30-day window.

        Uses `all_objects` on purpose. Withdrawing an application sets
        is_deleted=True, and the default manager hides those rows — so
        counting through `objects` would let a user apply, withdraw, and
        get the quota slot back. The quota measures submissions, not
        currently-open applications.
        """
        from datetime import timedelta

        from django.utils import timezone

        from apps.applications.models import Application

        cutoff = timezone.now() - timedelta(days=30)
        return Application.all_objects.filter(
            seeker__user=user,
            submitted_at__gte=cutoff,
        ).count()


class RefundService:
    """
    Admin-issued refunds.

    Razorpay refunds settle asynchronously: the API call returns almost
    immediately with status 'pending' and the money moves later, confirmed by
    the refund.processed webhook. So a Refund row starts PENDING and is only
    marked PROCESSED once that webhook arrives.
    """

    @classmethod
    def issue(cls, transaction_obj, reason, amount_inr=None, actor=None, revoke_access=None):
        """
        Refund a successful payment, in full or in part.

        Args:
            transaction_obj: the PaymentTransaction to refund
            reason: why (required - this is the accountability record)
            amount_inr: partial amount; None means the full remaining balance
            actor: the admin issuing it; None for system-initiated refunds
            revoke_access: end the subscription too. Defaults to True for a
                full refund and False for a partial one, which is the
                behaviour that matches what the money actually did.

        Not wrapped in transaction.atomic: the gateway call happens in the
        middle, and a failure record has to survive the error that follows it.
        """
        if not reason or not reason.strip():
            raise ValidationError({"reason": "A refund reason is required."})

        if transaction_obj.status != PaymentTransaction.Status.SUCCESS:
            raise ValidationError(
                {
                    "detail": "Only successful payments can be refunded "
                    f"(this one is {transaction_obj.status})."
                }
            )

        if not transaction_obj.razorpay_payment_id:
            raise ValidationError({"detail": "This transaction has no Razorpay payment id."})

        remaining = cls.refundable_amount(transaction_obj)
        if remaining <= 0:
            raise ValidationError({"detail": "This payment has already been fully refunded."})

        if amount_inr is None:
            amount_inr = remaining
        else:
            amount_inr = Decimal(str(amount_inr))
            if amount_inr <= 0:
                raise ValidationError({"amount_inr": "Amount must be positive."})
            if amount_inr > remaining:
                raise ValidationError(
                    {"amount_inr": f"Only Rs.{remaining} remains refundable " f"on this payment."}
                )

        is_full = amount_inr >= remaining
        if revoke_access is None:
            revoke_access = is_full

        refund = Refund.objects.create(
            transaction=transaction_obj,
            amount_inr=amount_inr,
            reason=reason.strip(),
            issued_by=actor,
            status=Refund.Status.PENDING,
        )

        try:
            result = RazorpayClient.refund_payment(
                payment_id=transaction_obj.razorpay_payment_id,
                amount_inr=amount_inr,
                notes={
                    "refund_id": str(refund.id),
                    "reason": reason.strip()[:200],
                    "issued_by": getattr(actor, "email", "system"),
                },
            )
        except Exception as e:
            refund.status = Refund.Status.FAILED
            refund.failure_reason = str(e)
            refund.save(update_fields=["status", "failure_reason"])
            logger.exception("Refund failed for transaction %s", transaction_obj.id)
            raise ValidationError({"detail": f"Refund failed at gateway: {e}"})

        refund.razorpay_refund_id = result.get("id", "")
        # A gateway that settles instantly reports 'processed' straight away
        if result.get("status") == "processed":
            refund.status = Refund.Status.PROCESSED
        refund.save(update_fields=["razorpay_refund_id", "status"])

        cls._apply_side_effects(refund, is_full, revoke_access)

        logger.info(
            "Refund %s of Rs.%s issued on transaction %s by %s",
            refund.razorpay_refund_id,
            amount_inr,
            transaction_obj.id,
            getattr(actor, "email", "system"),
        )
        return refund

    @staticmethod
    def refundable_amount(transaction_obj):
        """Original amount minus everything not already failed."""
        spent = transaction_obj.refunds.exclude(
            status=Refund.Status.FAILED,
        ).aggregate(
            total=Sum("amount_inr")
        )["total"] or Decimal("0")
        return transaction_obj.amount_inr - spent

    @classmethod
    @transaction.atomic
    def _apply_side_effects(cls, refund, is_full, revoke_access):
        """Mark the transaction refunded and, if asked, end the subscription."""
        txn = refund.transaction

        if is_full:
            txn.status = PaymentTransaction.Status.REFUNDED
            txn.save(update_fields=["status"])

        if not revoke_access:
            return

        subscription = txn.subscription
        if subscription and subscription.status in (
            Subscription.Status.ACTIVE,
            Subscription.Status.TRIALING,
        ):
            now = timezone.now()
            subscription.status = Subscription.Status.CANCELLED
            subscription.auto_renew = False
            subscription.cancelled_at = now
            # Refunded money means access ends now, not at period end.
            subscription.current_period_end = now
            subscription.cancellation_reason = f"Payment refunded: {refund.reason}"[:500]
            subscription.save(
                update_fields=[
                    "status",
                    "auto_renew",
                    "cancelled_at",
                    "current_period_end",
                    "cancellation_reason",
                ]
            )

        refund.access_revoked = True
        refund.save(update_fields=["access_revoked"])

    @classmethod
    def mark_processed(cls, razorpay_refund_id):
        """Called by the refund.processed webhook."""
        refund = Refund.objects.filter(
            razorpay_refund_id=razorpay_refund_id,
        ).first()
        if not refund:
            logger.warning("Unknown refund id in webhook: %s", razorpay_refund_id)
            return None

        if refund.status != Refund.Status.PROCESSED:
            refund.status = Refund.Status.PROCESSED
            refund.save(update_fields=["status"])
        return refund
