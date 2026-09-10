"""
Signal handlers for accounts app.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import OTPCode
from .services import OTPService


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def send_email_verification_on_signup(sender, instance, created, **kwargs):
    """
    When a new user is created, automatically send an email verification OTP.
    """
    if created and not instance.is_email_verified:
        # Skip for superusers (they're auto-verified)
        if not instance.is_superuser:
            try:
                OTPService.create_and_send(
                    user=instance,
                    purpose=OTPCode.Purpose.EMAIL_VERIFICATION,
                )
            except Exception as e:
                # Don't crash signup if email fails — just log and continue
                import logging

                logging.error(f"Failed to send OTP to {instance.email}: {e}")
