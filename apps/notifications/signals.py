import secrets

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import NotificationPreferences


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_notification_preferences(sender, instance, created, **kwargs):
    """Auto-create notification preferences when a new user signs up."""
    if created:
        NotificationPreferences.objects.get_or_create(
            user=instance,
            defaults={"unsubscribe_token": secrets.token_urlsafe(48)},
        )
