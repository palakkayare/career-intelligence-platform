"""
Signal handlers for the referrals app.
"""

import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ReferralCode, generate_unique_code

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_referral_code(sender, instance, created, **kwargs):
    """Automatically create a referral code when a new user signs up."""
    if not created:
        return
    try:
        ReferralCode.objects.get_or_create(
            user=instance,
            defaults={"code": generate_unique_code(instance)},
        )
    except Exception as exc:
        # Never break the signup flow because of referral code creation
        logger.error(f"Failed to create referral code for {instance}: {exc}")
