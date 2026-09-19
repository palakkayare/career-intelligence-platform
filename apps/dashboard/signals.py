"""
Drop a seeker's cached dashboard whenever something it shows changes.

Each receiver is registered on its own (not in a loop): Django keeps weak
references to receivers, and loop-built functions would be collected.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.applications.models import Application
from apps.career_intel.models import SkillGapSnapshot
from apps.jobs.models import SavedJob
from apps.payments.models import Subscription
from apps.resumes.models import Resume
from apps.seekers.models import SeekerProfile, SeekerSkill

from .services import invalidate


def _seeker_user_id(profile_id):
    return SeekerProfile.all_objects.filter(pk=profile_id).values_list("user_id", flat=True).first()


@receiver(post_save, sender=Application)
def _on_application_save(sender, instance, **kwargs):
    invalidate(_seeker_user_id(instance.seeker_id))


@receiver(post_save, sender=SeekerProfile)
def _on_profile_save(sender, instance, **kwargs):
    invalidate(instance.user_id)


@receiver(post_save, sender=SeekerSkill)
def _on_skill_save(sender, instance, **kwargs):
    invalidate(_seeker_user_id(instance.seeker_id))


@receiver(post_delete, sender=SeekerSkill)
def _on_skill_delete(sender, instance, **kwargs):
    invalidate(_seeker_user_id(instance.seeker_id))


@receiver(post_save, sender=Resume)
def _on_resume_save(sender, instance, **kwargs):
    invalidate(instance.user_id)


@receiver(post_delete, sender=Resume)
def _on_resume_delete(sender, instance, **kwargs):
    invalidate(instance.user_id)


@receiver(post_save, sender=SavedJob)
def _on_saved_job_save(sender, instance, **kwargs):
    invalidate(instance.user_id)


@receiver(post_delete, sender=SavedJob)
def _on_saved_job_delete(sender, instance, **kwargs):
    invalidate(instance.user_id)


@receiver(post_save, sender=Subscription)
def _on_subscription_save(sender, instance, **kwargs):
    invalidate(instance.user_id)


@receiver(post_save, sender=SkillGapSnapshot)
def _on_gap_snapshot_save(sender, instance, **kwargs):
    # "One skill to learn" reads the latest snapshot.
    invalidate(_seeker_user_id(instance.seeker_id))
