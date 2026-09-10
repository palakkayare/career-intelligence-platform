"""
Trigger recompute when relevant data changes.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.jobs.models import Job

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Job)
def trigger_recompute_for_job(sender, instance, created, **kwargs):
    """When a job is created or activated, queue match score computation."""
    # Only trigger for ACTIVE state (skip DRAFT)
    if instance.status != Job.Status.ACTIVE:
        return

    from .tasks import recompute_match_scores_for_job

    recompute_match_scores_for_job.delay(instance.id)
