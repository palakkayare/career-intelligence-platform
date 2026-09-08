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
        expired, failed = JobStatusService.expire_overdue()

        if failed:
            self.stderr.write(f'{failed} job(s) could not be expired.')
        self.stdout.write(self.style.SUCCESS(f'Expired {expired} job(s).'))