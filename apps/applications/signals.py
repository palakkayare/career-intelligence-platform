"""
Keep Job.application_count in sync.

The counter tracks *live* applications, so it has to follow withdrawal too.
Withdrawing is a soft delete (is_deleted flips to True) rather than a row
deletion, which means post_delete never fires — the change has to be caught
on save by comparing against the previous state.
"""
from django.db.models import F
from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from apps.jobs.models import Job
from .models import Application


def _shift(job_id, delta):
    Job.objects.filter(pk=job_id).update(
        application_count=F('application_count') + delta
    )


@receiver(post_init, sender=Application)
def remember_deleted_state(sender, instance, **kwargs):
    """Snapshot is_deleted at load time so post_save can spot a transition."""
    instance._was_deleted = instance.is_deleted


@receiver(post_save, sender=Application)
def sync_job_application_count(sender, instance, created, **kwargs):
    if created:
        if not instance.is_deleted:
            _shift(instance.job_id, 1)
    else:
        was_deleted = getattr(instance, '_was_deleted', instance.is_deleted)
        if not was_deleted and instance.is_deleted:
            _shift(instance.job_id, -1)      # withdrawn
        elif was_deleted and not instance.is_deleted:
            _shift(instance.job_id, 1)       # restored

    instance._was_deleted = instance.is_deleted