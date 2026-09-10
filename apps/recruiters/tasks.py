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

    logger.info("Reset %s recruiter credit cycles", count)
    return count


@shared_task
def sweep_talent_pools():
    """
    Daily: tell recruiters about new candidates in their saved pools.

    Blueprint Feature 15: "Talent Pool - saved searches that auto-update as
    new candidates join."
    """
    from .models import TalentPool
    from .services import TalentPoolService

    pools = TalentPool.objects.filter(
        notify_on_new=True,
    ).select_related("recruiter", "recruiter__user")

    notified = 0
    for pool in pools:
        try:
            if TalentPoolService.notify_new_members(pool):
                notified += 1
        except Exception:
            # One broken pool must not stop the sweep for everyone else.
            logger.exception("Talent pool sweep failed for pool %s", pool.pk)

    logger.info("Talent pool sweep: %s pools had new candidates", notified)
    return {"pools_with_new_candidates": notified}
