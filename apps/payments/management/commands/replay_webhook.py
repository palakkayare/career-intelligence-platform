"""
Replay a webhook event by ID. Useful for debugging.
Usage: python manage.py replay_webhook <event_id>
"""

from django.core.management.base import BaseCommand

from apps.payments.models import WebhookEvent
from apps.payments.webhook_handlers import process_event


class Command(BaseCommand):
    help = "Replay processing of a webhook event"

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=str, help="Razorpay event ID")

    def handle(self, *args, **options):
        event_id = options["event_id"]
        try:
            event = WebhookEvent.objects.get(razorpay_event_id=event_id)
        except WebhookEvent.DoesNotExist:
            self.stderr.write(f"Event {event_id} not found.")
            return

        self.stdout.write(f"Replaying {event.event_type}...")
        try:
            process_event(event)
        except Exception as e:
            event.processing_status = WebhookEvent.ProcessingStatus.FAILED
            event.error_message = str(e)[:1000]
            event.retry_count += 1
            event.save()
            self.stdout.write(self.style.ERROR(f"Failed: {e}"))
            return

        from django.utils import timezone

        event.processing_status = WebhookEvent.ProcessingStatus.PROCESSED
        event.processed_at = timezone.now()
        event.error_message = ""
        event.save()
        self.stdout.write(self.style.SUCCESS("Success!"))
