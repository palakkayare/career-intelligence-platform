"""
Keep Job.search_vector in sync when title/description change.
"""
from django.contrib.postgres.search import SearchVector
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Job


def update_search_vector(job_id):
    """Recompute search_vector for a job."""
    Job.objects.filter(pk=job_id).update(
        search_vector=(
            SearchVector('title', weight='A') +
            SearchVector('description', weight='B')
        )
    )


@receiver(post_save, sender=Job)
def update_job_search_vector(sender, instance, **kwargs):
    """Update vector after save."""
    # Avoid recursion — only run if relevant fields changed (or always for simplicity)
    update_fields = kwargs.get('update_fields')
    if update_fields and 'search_vector' in update_fields:
        return  # We're in the middle of updating it

    update_search_vector(instance.pk)