"""Auto-create SeekerProfile when a user with role='seeker' signs up."""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import SeekerProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_seeker_profile(sender, instance, created, **kwargs):
    if created and instance.role == 'seeker':
        SeekerProfile.objects.get_or_create(
            user=instance,
            defaults={'full_name': instance.full_name or ''},
        )