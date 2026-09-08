"""
Celery tasks for recruiter operations.
"""

import logging
from datetime import date, timedelta

from celery import shared_task

from .models import RecruiterCredits

logger = logging.getLogger(__name__)


@shared_task
def reset_expired_credit_cycles():
    """
    Daily job: start a new cycle for every recruiter whose 30-day
    window has ended. Runs via Celery Beat at 00:30 IST.
    """
    cutoff = date.today() - timedelta(days=30)

    expired = RecruiterCredits.objects.filter(cycle_starts_on__lte=cutoff)

    count = 0
    for credits in expired.iterator():
        credits.reset_cycle()
        count += 1

    logger.info('Reset %s recruiter credit cycles', count)
    return count