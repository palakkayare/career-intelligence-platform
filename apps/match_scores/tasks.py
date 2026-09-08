"""
Celery tasks for match score (re)computation.
"""
import logging

from celery import shared_task

from apps.jobs.models import Job
from apps.seekers.models import SeekerProfile
from .services import MatchScoreService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def recompute_match_scores_for_job(self, job_id):
    """
    Recompute match scores for one job x all relevant seekers.
    Triggered when: job created, job updated, or via batch.
    """
    try:
        job = Job.objects.get(pk=job_id, is_deleted=False)
    except Job.DoesNotExist:
        logger.warning(f"Job {job_id} not found for recompute")
        return

    if job.status != Job.Status.ACTIVE:
        logger.info(f"Job {job_id} not active, skipping")
        return

    # Find candidate seekers — those with overlap in required skills
    required_skill_ids = list(
        job.required_skills.values_list('id', flat=True)
    )
    if not required_skill_ids:
        logger.info(f"Job {job_id} has no required skills, skipping")
        return

    seekers = (
        SeekerProfile.objects
        .filter(
            user__is_active=True,
            user__is_email_verified=True,
            seeker_skills__skill_id__in=required_skill_ids,
            is_deleted=False,
        )
        .distinct()
    )

    count = 0
    for seeker in seekers:
        try:
            MatchScoreService.compute_and_save(seeker, job)
            count += 1
        except Exception as e:
            logger.error(f"Failed for seeker {seeker.id}: {e}")

    logger.info(f"Job {job_id}: computed {count} match scores")
    return count


@shared_task
def recompute_all_match_scores():
    """
    Periodic task: recompute scores for ALL active jobs.
    Triggered by Celery Beat every 6 hours.
    """
    active_jobs = Job.objects.filter(
        status=Job.Status.ACTIVE,
        is_deleted=False,
    ).values_list('id', flat=True)

    job_count = 0
    for job_id in active_jobs:
        # Queue a per-job task (parallel processing across jobs)
        recompute_match_scores_for_job.delay(job_id)
        job_count += 1

    logger.info(f"Queued recompute for {job_count} active jobs")
    return job_count