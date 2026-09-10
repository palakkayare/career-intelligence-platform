"""
Business logic for the referral system.
"""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Referral, ReferralCode, ReferralReward, generate_unique_code

logger = logging.getLogger(__name__)

# --- Reward configuration ---
REFERRER_PRO_DAYS = 30
REFEREE_DISCOUNT_PCT = 50
REFEREE_DISCOUNT_VALIDITY_DAYS = 30
REFERRER_REWARD_VALIDITY_DAYS = 90
MAX_REWARDS_PER_REFERRER_PER_MONTH = 10

# Sharing a domain with these providers is normal, so it is not suspicious
PUBLIC_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "protonmail.com",
    "proton.me",
}


class ReferralService:
    """All referral operations live here; views stay thin."""

    # ─── Code management ───

    @classmethod
    def get_or_create_code(cls, user) -> ReferralCode:
        """Return the user's referral code, generating one if missing."""
        code, _created = ReferralCode.objects.get_or_create(
            user=user,
            defaults={"code": generate_unique_code(user)},
        )
        return code

    @classmethod
    def track_click(cls, code_str: str) -> None:
        """Increment the click counter for a referral code."""
        if not code_str:
            return
        # F() expression keeps the increment atomic at the database level
        ReferralCode.objects.filter(
            code=code_str.upper().strip(),
            is_active=True,
        ).update(click_count=F("click_count") + 1)

    # ─── Signup linking ───

    @classmethod
    @transaction.atomic
    def attach_referral_on_signup(cls, referee_user, code_str: str, ip_address=None):
        """
        Called from the registration flow when a `ref` parameter is present.

        Creates a Referral row in the pending state. Returns None (silently)
        whenever the referral is invalid, so signup never fails because of it.
        """
        if not code_str:
            return None

        code_str = code_str.upper().strip()

        try:
            code = ReferralCode.objects.select_for_update().get(
                code=code_str,
                is_active=True,
            )
        except ReferralCode.DoesNotExist:
            logger.warning(f"Referral code not found: {code_str}")
            return None

        # Rule 1: a user cannot refer themselves
        if code.user_id == referee_user.id:
            logger.warning(f"Self-referral attempt by {referee_user.email}")
            return None

        # Rule 2: every user can be referred only once
        if Referral.objects.filter(referee=referee_user).exists():
            logger.warning(f"User {referee_user.email} was already referred")
            return None

        # Rule 3: matching private email domains look like farmed accounts
        referrer_domain = code.user.email.split("@")[-1].lower()
        referee_domain = referee_user.email.split("@")[-1].lower()
        is_flagged = (
            referrer_domain == referee_domain and referrer_domain not in PUBLIC_EMAIL_DOMAINS
        )

        referral = Referral.objects.create(
            referrer=code.user,
            referee=referee_user,
            code_used=code,
            status=Referral.Status.FLAGGED if is_flagged else Referral.Status.PENDING,
            referee_signup_ip=ip_address,
            is_flagged=is_flagged,
            flag_reason="Same private email domain (suspicious)" if is_flagged else "",
        )

        ReferralCode.objects.filter(pk=code.pk).update(
            signup_count=F("signup_count") + 1,
        )

        logger.info(f"Referral created: {code.user.email} -> {referee_user.email}")
        return referral

    # ─── Conversion ───

    @classmethod
    @transaction.atomic
    def trigger_conversion(cls, user, transaction_obj):
        """
        Called from the payment flow when a paid subscription is activated.

        Marks the pending referral as converted and creates rewards for
        both sides. Flagged referrals are ignored on purpose.
        """
        referral = (
            Referral.objects.select_for_update()
            .filter(referee=user, status=Referral.Status.PENDING)
            .first()
        )
        if not referral:
            return None

        # Only the FIRST paid subscription counts as a conversion
        from apps.payments.models import PaymentTransaction

        previous_paid = (
            PaymentTransaction.objects.filter(user=user, status=PaymentTransaction.Status.SUCCESS)
            .exclude(pk=transaction_obj.pk)
            .exists()
        )
        if previous_paid:
            logger.info(
                f"User {user.email} already had a paid transaction "
                f"- skipping referral conversion"
            )
            return None

        # Anti-farming: enforce the referrer's monthly reward cap
        last_30_days = timezone.now() - timedelta(days=30)
        recent_conversions = Referral.objects.filter(
            referrer=referral.referrer,
            status=Referral.Status.CONVERTED,
            converted_at__gte=last_30_days,
        ).count()

        if recent_conversions >= MAX_REWARDS_PER_REFERRER_PER_MONTH:
            logger.warning(
                f"Referrer {referral.referrer.email} hit the monthly cap "
                f"({recent_conversions}/{MAX_REWARDS_PER_REFERRER_PER_MONTH})"
            )
            referral.status = Referral.Status.FLAGGED
            referral.is_flagged = True
            referral.flag_reason = "Referrer hit the monthly reward cap"
            referral.save(update_fields=["status", "is_flagged", "flag_reason"])
            return None

        # Mark the referral as converted
        referral.status = Referral.Status.CONVERTED
        referral.converted_at = timezone.now()
        referral.converted_amount_inr = transaction_obj.amount_inr
        referral.save(update_fields=["status", "converted_at", "converted_amount_inr"])

        if referral.code_used_id:
            ReferralCode.objects.filter(pk=referral.code_used_id).update(
                paid_count=F("paid_count") + 1,
            )

        cls._create_rewards(referral)
        cls._notify_conversion(referral)

        return referral

    @classmethod
    def _create_rewards(cls, referral) -> None:
        """Create one ReferralReward row for the referrer and one for the referee."""
        now = timezone.now()

        # Referrer reward: extra Pro days on the next renewal
        ReferralReward.objects.create(
            referral=referral,
            user=referral.referrer,
            kind=ReferralReward.Kind.PRO_EXTENSION,
            value={"days": REFERRER_PRO_DAYS},
            status=ReferralReward.Status.GRANTED,
            granted_at=now,
            expires_at=now + timedelta(days=REFERRER_REWARD_VALIDITY_DAYS),
        )

        # Referee reward: the referee has already paid, so give them a
        # discount code they can use on the next purchase
        discount_code = f"REF-{secrets.token_hex(3).upper()}"
        ReferralReward.objects.create(
            referral=referral,
            user=referral.referee,
            kind=ReferralReward.Kind.DISCOUNT,
            value={
                "percent_off": REFEREE_DISCOUNT_PCT,
                "code": discount_code,
                "description": (f"{REFEREE_DISCOUNT_PCT}% off your next subscription"),
            },
            status=ReferralReward.Status.GRANTED,
            granted_at=now,
            expires_at=now + timedelta(days=REFEREE_DISCOUNT_VALIDITY_DAYS),
        )

    @classmethod
    def _notify_conversion(cls, referral) -> None:
        """Send an in-app notification to both sides of the referral."""
        from apps.notifications.models import NotificationKind
        from apps.notifications.service import NotificationService

        try:
            NotificationService.create(
                user=referral.referrer,
                kind=NotificationKind.PAYMENT_SUCCESS,  # reused until a referral kind exists
                title="Your referral converted!",
                message=(
                    f"{referral.referee.email} just subscribed using your code. "
                    f"You earned {REFERRER_PRO_DAYS} days of Pro on your next renewal."
                ),
                link="/referrals/my-rewards/",
                context={"referee_email": referral.referee.email},
            )

            NotificationService.create(
                user=referral.referee,
                kind=NotificationKind.PAYMENT_SUCCESS,
                title="Welcome bonus unlocked!",
                message=(
                    f"You signed up with a referral code. "
                    f"Enjoy {REFEREE_DISCOUNT_PCT}% off your next subscription."
                ),
                link="/referrals/my-rewards/",
                context={},
            )
        except Exception as exc:
            # Notification failure must never roll back a conversion
            logger.error(f"Failed to notify referral conversion: {exc}")

    # ─── Reward redemption ───

    @classmethod
    @transaction.atomic
    def apply_pro_extension_reward(cls, user, reward_id) -> bool:
        """Extend the user's active subscription by reward.value['days']."""
        try:
            reward = ReferralReward.objects.select_for_update().get(
                pk=reward_id,
                user=user,
                kind=ReferralReward.Kind.PRO_EXTENSION,
                status=ReferralReward.Status.GRANTED,
            )
        except ReferralReward.DoesNotExist:
            raise ValidationError("Reward not found or already used.")

        if not reward.is_usable():
            raise ValidationError("This reward has expired.")

        from apps.payments.models import Subscription

        sub = (
            Subscription.objects.select_for_update()
            .filter(
                user=user,
                status=Subscription.Status.ACTIVE,
            )
            .first()
        )

        if not sub:
            raise ValidationError(
                "No active subscription to extend. Subscribe first, " "then apply the reward."
            )

        days = reward.value.get("days", 0)
        sub.current_period_end = sub.current_period_end + timedelta(days=days)
        sub.save(update_fields=["current_period_end"])

        reward.status = ReferralReward.Status.USED
        reward.used_at = timezone.now()
        reward.save(update_fields=["status", "used_at"])

        logger.info(f"Applied a {days}-day Pro extension for {user.email}")
        return True

    # ─── Read APIs ───

    @classmethod
    def get_my_stats(cls, user) -> dict:
        """Return the user's own funnel metrics."""
        code = cls.get_or_create_code(user)

        return {
            "code": code.code,
            "share_url": f"{settings.FRONTEND_URL}/signup?ref={code.code}",
            "click_count": code.click_count,
            "signup_count": code.signup_count,
            "paid_count": code.paid_count,
            "conversion_rate": (
                round(code.paid_count / code.signup_count * 100, 1)
                if code.signup_count > 0
                else 0.0
            ),
        }

    @classmethod
    def get_leaderboard(cls, limit: int = 20) -> list:
        """Top referrers ranked by paid conversions over the last 30 days."""
        last_30 = timezone.now() - timedelta(days=30)

        return list(
            Referral.objects.filter(status=Referral.Status.CONVERTED, converted_at__gte=last_30)
            .values("referrer__id", "referrer__email", "referrer__full_name")
            .annotate(conversion_count=Count("id"))
            .order_by("-conversion_count")[:limit]
        )
