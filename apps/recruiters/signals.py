from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import RecruiterProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_recruiter_profile(sender, instance, created, **kwargs):
    if created and instance.role == 'recruiter':
        RecruiterProfile.objects.get_or_create(
            user=instance,
            defaults={'full_name': instance.full_name or ''},
        )