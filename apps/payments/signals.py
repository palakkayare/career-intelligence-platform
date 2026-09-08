"""
Auto-grant free trial on user signup.
"""
import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .services import SubscriptionService

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def grant_free_trial_on_signup(sender, instance, created, **kwargs):
    """
    When a new user is created, grant 7-day Pro trial.
    Skip for admins.
    """
    if not created:
        return

    if instance.role == 'admin':
        return

    try:
        SubscriptionService.grant_free_trial(instance)
    except Exception as e:
        # Don't crash signup if subscription creation fails
        logger.error(f"Failed to grant trial to {instance.email}: {e}")