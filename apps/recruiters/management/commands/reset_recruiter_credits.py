from django.core.management.base import BaseCommand

from apps.recruiters.tasks import reset_expired_credit_cycles


class Command(BaseCommand):
    help = "Manually trigger the recruiter credit cycle reset"

    def handle(self, *args, **options):
        count = reset_expired_credit_cycles()
        self.stdout.write(self.style.SUCCESS(f"Reset {count} credit cycles."))
