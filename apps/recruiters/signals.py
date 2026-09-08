from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import RecruiterProfile, RecruiterCredits


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_recruiter_profile(sender, instance, created, **kwargs):
    if created and instance.role == 'recruiter':
        RecruiterProfile.objects.get_or_create(
            user=instance,
            defaults={'full_name': instance.full_name or ''},
        )
        
@receiver(post_save, sender=RecruiterProfile)
def create_recruiter_credits(sender, instance, created, **kwargs):
    """Create an empty credit wallet as soon as a recruiter profile exists."""
    if created:
        RecruiterCredits.objects.get_or_create(
            recruiter=instance,
            defaults={
                # Starts at zero; the real limit is set when a plan is activated
                'monthly_reveal_limit': 0,
            },
        )