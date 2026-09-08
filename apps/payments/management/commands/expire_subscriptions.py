"""
Mark subscriptions whose period has ended as EXPIRED.

Phase 2: run manually or via cron.
Later: replaced by a Celery Beat daily schedule (Step 16+).

Usage: python manage.py expire_subscriptions
"""
from django.core.management.base import BaseCommand

from apps.payments.services import SubscriptionService


class Command(BaseCommand):
    help = 'Auto-expire subscriptions whose period has ended'

    def handle(self, *args, **options):
        count = SubscriptionService.expire_ended_subscriptions()
        self.stdout.write(self.style.SUCCESS(
            f'Expired {count} subscription(s).'
        ))