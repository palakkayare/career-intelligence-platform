"""
Keep Job.application_count in sync.
"""
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.jobs.models import Job
from .models import Application


@receiver(post_save, sender=Application)
def increment_job_application_count(sender, instance, created, **kwargs):
    """Increment job counter when new application is created."""
    if created and not instance.is_deleted:
        Job.objects.filter(pk=instance.job_id).update(
            application_count=F('application_count') + 1
        )