"""
Trigger recompute when relevant data changes.
"""

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.jobs.models import Job
from apps.seekers.models import SeekerProfile, SeekerSkill

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Job)
def trigger_recompute_for_job(sender, instance, created, **kwargs):
    """When a job is created or activated, queue match score computation."""
    # Only trigger for ACTIVE state (skip DRAFT)
    if instance.status != Job.Status.ACTIVE:
        return

    from .tasks import recompute_match_scores_for_job

    recompute_match_scores_for_job.delay(instance.id)


# ── Seeker side ───────────────────────────────────────────────────────
# A score depends on the seeker's skills, experience and location as much as
# on the job. Each receiver is registered on its own; Django holds receivers
# by weak reference, so loop-built functions would be collected.

# Fields compute_and_save reads. A profile save that touches none of them
# (a new photo, a bio edit) queues nothing.
_SCORING_FIELDS = {"years_of_experience", "location"}


@receiver(post_save, sender=SeekerSkill)
def recompute_on_skill_saved(sender, instance, **kwargs):
    from .tasks import queue_seeker_recompute

    queue_seeker_recompute(instance.seeker_id)


@receiver(post_delete, sender=SeekerSkill)
def recompute_on_skill_deleted(sender, instance, **kwargs):
    from .tasks import queue_seeker_recompute

    queue_seeker_recompute(instance.seeker_id)


@receiver(post_save, sender=SeekerProfile)
def recompute_on_profile_saved(sender, instance, created, update_fields=None, **kwargs):
    if created:
        return  # a brand-new profile has no skills to score yet
    if update_fields is not None and not (_SCORING_FIELDS & set(update_fields)):
        return
    from .tasks import queue_seeker_recompute

    queue_seeker_recompute(instance.pk)
