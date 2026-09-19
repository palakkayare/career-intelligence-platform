"""
Recompute match scores now, without waiting for Celery Beat.

    python manage.py recompute_match_scores                 # every seeker
    python manage.py recompute_match_scores --email a@b.com # one seeker

Runs in this process (no worker needed), so it also works right after
loading data or on a machine where only the web server is running.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.match_scores.tasks import recompute_match_scores_for_seeker
from apps.seekers.models import SeekerProfile


class Command(BaseCommand):
    help = "Recompute match scores for one seeker or for all of them."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Only this seeker")

    def handle(self, *args, **options):
        seekers = SeekerProfile.objects.filter(is_deleted=False, user__is_active=True)
        if options["email"]:
            seekers = seekers.filter(user__email__iexact=options["email"])
            if not seekers.exists():
                raise CommandError(f"No active seeker with email {options['email']}")

        total = 0
        for seeker_id in seekers.values_list("pk", flat=True):
            total += recompute_match_scores_for_seeker.run(seeker_id) or 0

        self.stdout.write(
            self.style.SUCCESS(f"Computed {total} match scores for {seekers.count()} seeker(s).")
        )
