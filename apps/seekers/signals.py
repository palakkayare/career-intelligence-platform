"""
Seeker profile signals.

Two jobs: create the profile on signup, and keep profile_strength in step
with the rows that feed it.
"""
from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Education, SeekerProfile, SeekerSkill, WorkExperience
from .services import ProfileStrengthService


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_seeker_profile(sender, instance, created, **kwargs):
    if created and instance.role == 'seeker':
        SeekerProfile.objects.get_or_create(
            user=instance,
            defaults={'full_name': instance.full_name or ''},
        )


def _refresh_strength(profile):
    if profile is not None:
        ProfileStrengthService.refresh(profile)


@receiver(post_save, sender=SeekerProfile)
def refresh_strength_on_profile_change(sender, instance, **kwargs):
    _refresh_strength(instance)


# Registered one by one rather than in a loop. Django holds receivers with
# weak references, and functions built inside a loop share a name - all but
# the last get collected and silently stop firing.

@receiver(post_save, sender=SeekerSkill)
@receiver(post_delete, sender=SeekerSkill)
def refresh_strength_on_skill_change(sender, instance, **kwargs):
    _refresh_strength(instance.seeker)


@receiver(post_save, sender=WorkExperience)
@receiver(post_delete, sender=WorkExperience)
def refresh_strength_on_experience_change(sender, instance, **kwargs):
    _refresh_strength(instance.seeker)


@receiver(post_save, sender=Education)
@receiver(post_delete, sender=Education)
def refresh_strength_on_education_change(sender, instance, **kwargs):
    _refresh_strength(instance.seeker)