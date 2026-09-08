"""
Scheduled jobs for the jobs app.
"""
import logging

from celery import shared_task

from .services import JobStatusService

logger = logging.getLogger(__name__)


@shared_task
def expire_jobs_task():
    """Nightly sweep: close out jobs past their application deadline."""
    expired, failed = JobStatusService.expire_overdue()
    logger.info('Job expiry sweep: %s expired, %s failed', expired, failed)
    return {'expired': expired, 'failed': failed}