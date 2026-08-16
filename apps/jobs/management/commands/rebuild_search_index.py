"""
Recompute search_vector for all jobs.
Usage: python manage.py rebuild_search_index
"""
from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand

from apps.jobs.models import Job


class Command(BaseCommand):
    help = 'Recompute search_vector for all jobs'

    def handle(self, *args, **options):
        count = Job.objects.update(
            search_vector=(
                SearchVector('title', weight='A') +
                SearchVector('description', weight='B')
            )
        )
        self.stdout.write(self.style.SUCCESS(f"Updated {count} jobs."))