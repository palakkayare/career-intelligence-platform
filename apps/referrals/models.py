"""
Referral system models: codes, referral instances and rewards.
"""

import secrets
import string

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel

# Ambiguous characters are excluded so a code can be shared verbally
# without confusion: O vs 0, I vs 1 vs L.
ALLOWED_CHARS = ''.join(
    c for c in (string.ascii_uppercase + string.digits) if c not in 'O0I1L'
)


def generate_unique_code(user, max_attempts: int = 10) -> str:
    """
    Generate a unique referral code in the format NAME-XXXX.

    Example: "PRIYA-X4F9". Retries on collision, then falls back to a
    fully random code.
    """
        # Different user models expose the name differently, so try the common
    # options in order and fall back to the email prefix.
    raw_name = (
        getattr(user, 'first_name', '')
        or (getattr(user, 'full_name', '') or '').split(' ')[0]
        or (getattr(user, 'email', '') or '').split('@')[0]
    )

    name_part = raw_name[:6].upper()
    # Keep letters and digits only, so the code stays URL safe
    name_part = ''.join(c for c in name_part if c.isalnum()) or 'USER'
    for _ in range(max_attempts):
        random_part = ''.join(secrets.choice(ALLOWED_CHARS) for _ in range(4))
        code = f"{name_part}-{random_part}"
        if not ReferralCode.objects.filter(code=code).exists():
            return code

    # Fallback: collision probability here is negligible
    return f"REF-{secrets.token_hex(4).upper()}"


class ReferralCode(TimestampedModel):
    """
    Permanent referral code owned by a single user.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referral_code',
    )
    code = models.CharField(max_length=20, unique=True, db_index=True)

    # Funnel counters
    click_count = models.PositiveIntegerField(default=0)
    signup_count = models.PositiveIntegerField(default=0)
    paid_count = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'referral_codes'

    def __str__(self):
        return f"{self.code} ({self.user.email})"


class Referral(TimestampedModel):
    """
    A single referral instance: tracks one referee through the funnel.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending (signed up)'
        CONVERTED = 'converted', 'Converted (paid)'
        EXPIRED = 'expired', 'Expired'
        FLAGGED = 'flagged', 'Flagged (abuse review)'

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referrals_made',
    )
    # OneToOne: a user can be referred only once, ever
    referee = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referral_received',
    )
    code_used = models.ForeignKey(
        ReferralCode,
        on_delete=models.SET_NULL,
        null=True,
        related_name='referrals',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # Timeline
    signup_at = models.DateTimeField(auto_now_add=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    converted_amount_inr = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )

    # Audit trail for abuse review
    referee_signup_ip = models.GenericIPAddressField(null=True, blank=True)
    is_flagged = models.BooleanField(default=False)
    flag_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'referrals'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['referrer', 'status']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.referrer.email} -> {self.referee.email} [{self.status}]"


class ReferralReward(TimestampedModel):
    """
    Reward granted to either the referrer or the referee on conversion.
    """

    class Kind(models.TextChoices):
        PRO_EXTENSION = 'pro_extension', 'Pro Subscription Extension'
        DISCOUNT = 'discount', 'Discount Code'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending Grant'
        GRANTED = 'granted', 'Granted (available to use)'
        USED = 'used', 'Used'
        EXPIRED = 'expired', 'Expired'

    referral = models.ForeignKey(
        Referral,
        on_delete=models.CASCADE,
        related_name='rewards',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referral_rewards',
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)

    # Payload shape depends on kind:
    #   pro_extension -> {"days": 30}
    #   discount      -> {"percent_off": 50, "code": "REF-A1B2C3"}
    value = models.JSONField(default=dict)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    granted_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    # Every reward must expire, otherwise it becomes an open-ended liability
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'referral_rewards'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status', 'expires_at']),
        ]

    def __str__(self):
        return f"{self.kind} for {self.user.email} [{self.status}]"

    def is_usable(self) -> bool:
        """Return True if this reward can be redeemed right now."""
        if self.status != self.Status.GRANTED:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True
    
    @classmethod
    def expire_stale(cls, user=None):
        """Flip granted rewards whose expiry has passed. Returns rows updated."""
        qs = cls.objects.filter(
            status=cls.Status.GRANTED,
            expires_at__lt=timezone.now(),
        )
        if user is not None:
            qs = qs.filter(user=user)
        return qs.update(status=cls.Status.EXPIRED)