"""
Queue the advanced ATS analysis for parsed resumes that never had one.

Resumes parsed before the advanced analysis existed were never queued, and
nothing would ever queue them. Their owners saw "no analysis" indefinitely.

    python manage.py queue_missing_advanced_ats --dry-run
    python manage.py queue_missing_advanced_ats

Safe to re-run: a resume with a result, or one already queued and still
within the patience window, is skipped. Needs a worker running to have any
effect.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.resumes.models import Resume
from apps.resumes.tasks import queue_advanced_ats
from apps.resumes.views import ADVANCED_ATS_PATIENCE


class Command(BaseCommand):
    help = "Queue advanced ATS analysis for parsed resumes that have no result."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be queued without queuing anything.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Queue at most this many, so a large backlog can go out in batches.",
        )

    def handle(self, *args, **options):
        gave_up_before = timezone.now() - ADVANCED_ATS_PATIENCE

        pending = Resume.objects.filter(
            status=Resume.Status.PARSED,
            advanced_ats_analyzed_at__isnull=True,
            is_deleted=False,
        ).exclude(advanced_ats_queued_at__gt=gave_up_before)

        total = pending.count()
        if options["limit"]:
            pending = pending.order_by("created_at")[: options["limit"]]

        if options["dry_run"]:
            self.stdout.write(f"Would queue {len(pending)} of {total} resume(s) without analysis.")
            return

        queued = 0
        for resume in pending:
            queue_advanced_ats(resume)
            queued += 1

        self.stdout.write(
            self.style.SUCCESS(f"Queued {queued} of {total} resume(s) without analysis.")
        )
