"""
Mark jobs whose deadline has passed as EXPIRED.
Phase 1: Run manually via cron / management command.
Phase 2: Migrate to Celery Beat.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.jobs.models import Job
from apps.jobs.services import JobStatusService


class Command(BaseCommand):
    help = 'Auto-expire jobs whose deadline has passed'

    def handle(self, *args, **options):
        now = timezone.now()
        expired = 0

        candidates = Job.objects.filter(
            status=Job.Status.ACTIVE,
            application_deadline__lt=now,
            is_deleted=False,
        )

        for job in candidates:
            try:
                JobStatusService.expire(job)
                expired += 1
            except Exception as e:
                self.stderr.write(f"Failed to expire {job.id}: {e}")

        self.stdout.write(self.style.SUCCESS(
            f"Expired {expired} job(s)."
        ))