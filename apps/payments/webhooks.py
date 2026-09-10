"""
Razorpay webhook receiver.
"""

import json
import logging

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import WebhookEvent
from .razorpay_client import RazorpayClient
from .webhook_handlers import process_event

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """
    POST /api/v1/webhooks/razorpay/

    Razorpay calls this on every event.

    Critical: ALWAYS return 200 if signature is valid.
    Failures during processing should be logged + retried separately.
    """
    # 1. Get raw body (BEFORE parsing — signature is on raw bytes)
    raw_body = request.body.decode("utf-8")
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not signature:
        logger.warning("Webhook received without signature header")
        return JsonResponse({"error": "Missing signature"}, status=400)

    # 2. Verify signature (auth)
    try:
        RazorpayClient.verify_webhook_signature(raw_body, signature)
    except Exception as e:
        logger.warning(f"Webhook signature verification failed: {e}")
        return JsonResponse({"error": "Invalid signature"}, status=400)

    # 3. Parse payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Webhook body is not valid JSON")
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Razorpay sends the unique event ID in a header, not the body
    event_id = (
        request.headers.get("X-Razorpay-Event-Id") or payload.get("id") or payload.get("event_id")
    )
    event_type = payload.get("event")

    if not event_id or not event_type:
        logger.error(f"Webhook missing event id/type: {payload}")
        return JsonResponse({"error": "Missing event id or type"}, status=400)

    # 4. Idempotency — check if already processed
    existing = WebhookEvent.objects.filter(
        razorpay_event_id=event_id,
    ).first()

    if existing and existing.processing_status == WebhookEvent.ProcessingStatus.PROCESSED:
        logger.info(f"Duplicate webhook event {event_id} — already processed, skipping.")
        return JsonResponse({"status": "already_processed"}, status=200)

    # 5. Save (or update) event
    if existing:
        # Was previously failed — retry
        existing.retry_count += 1
        existing.processing_status = WebhookEvent.ProcessingStatus.RECEIVED
        existing.error_message = ""
        existing.save()
        event = existing
    else:
        event = WebhookEvent.objects.create(
            razorpay_event_id=event_id,
            event_type=event_type,
            payload=payload,
            signature=signature,
            processing_status=WebhookEvent.ProcessingStatus.RECEIVED,
        )

    # 6. Process the event
    try:
        process_event(event)
        event.processing_status = WebhookEvent.ProcessingStatus.PROCESSED
        event.processed_at = timezone.now()
        event.error_message = ""
        event.save()
        logger.info(f"Webhook {event_id} ({event_type}) processed successfully")
    except Exception as e:
        # Log error, but STILL return 200
        # We don't want Razorpay to retry forever for our bugs
        logger.exception(f"Webhook {event_id} processing failed: {e}")
        event.processing_status = WebhookEvent.ProcessingStatus.FAILED
        event.error_message = str(e)[:1000]
        event.save()

    # 7. Always return 200 if signature was valid
    return JsonResponse({"status": "ok", "event_id": event_id}, status=200)
