"""
Celery tasks for email delivery.
Keeping email out of the request cycle keeps API responses fast.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from .models import DeliveryPriority, Notification, NotificationPreferences

logger = logging.getLogger(__name__)


# Maps a notification kind to its template directory under templates/emails/
KIND_TEMPLATES = {
    "app_status_change": "application_status_change",
    "application_received": "application_received",
    "payment_success": "payment_success",
    "payment_failed": "payment_failed",
    "sub_expiring": "subscription_expiring",
    "sub_expired": "subscription_expired",
    "job_approved": "job_approved",
    "job_rejected": "job_rejected",
    "app_withdrawn": "application_withdrawn",
    "resume_analysed": "resume_analysis_complete",
    # These two are only ever sent as part of the daily digest
    "new_matching_job": "new_matching_jobs_digest",
    "new_matching_candidate": "new_matching_candidates_digest",
}


def _build_context(notif):
    """Build the template context from the notification and its user."""
    user = notif.user

    try:
        unsubscribe_token = user.notification_preferences.unsubscribe_token
    except NotificationPreferences.DoesNotExist:
        unsubscribe_token = ""

    context = {
        "user": user,
        "user_name": getattr(user, "full_name", "") or user.email,
        "notification": notif,
        "title": notif.title,
        "message": notif.message,
        # Turn the relative deep link into an absolute URL for the email
        "link": f"{settings.FRONTEND_URL}{notif.link}" if notif.link else "",
        "frontend_url": settings.FRONTEND_URL,
        "unsubscribe_url": (
            f"{settings.FRONTEND_URL}/unsubscribe/{unsubscribe_token}" if unsubscribe_token else ""
        ),
        "support_email": settings.SUPPORT_EMAIL,
        # Custom values passed in by the trigger override the defaults above
        **notif.context,
    }
    return context


def _build_attachments(notif):
    """
    Files to attach for this notification kind, if any.

    Only payment confirmations carry one today: the GST invoice, which people
    need for their own books. The import is local so the notifications app
    does not depend on payments at module level.
    """
    if notif.kind != "payment_success":
        return []

    transaction_id = notif.context.get("transaction_id")
    if not transaction_id:
        return []

    from apps.payments.invoice_pdf import build_invoice_attachment
    from apps.payments.models import PaymentTransaction

    txn = PaymentTransaction.objects.filter(pk=transaction_id).first()
    if txn is None:
        return []

    attachment = build_invoice_attachment(txn)
    return [attachment] if attachment else []


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_notification_email(self, notification_id):
    """
    Send one notification as an email.
    Retries up to 3 times on network issues or SendGrid errors.
    """
    try:
        notif = Notification.objects.select_related("user").get(pk=notification_id)
    except Notification.DoesNotExist:
        logger.error("Notification %s not found", notification_id)
        return

    # Guard against duplicate sends when a task is retried or re-queued
    if notif.is_emailed:
        logger.info("Notification %s already emailed, skipping", notification_id)
        return

    template_dir = KIND_TEMPLATES.get(notif.kind)
    if not template_dir:
        logger.warning("No email template for kind %s", notif.kind)
        return

    context = _build_context(notif)

    try:
        subject = render_to_string(
            f"emails/{template_dir}/subject.txt",
            context,
        ).strip()
        body_text = render_to_string(
            f"emails/{template_dir}/body.txt",
            context,
        )
        body_html = render_to_string(
            f"emails/{template_dir}/body.html",
            context,
        )

        # Multipart email: plain text body + HTML alternative.
        # Sending both improves deliverability and accessibility.
        msg = EmailMultiAlternatives(
            subject=subject,
            body=body_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[notif.user.email],
        )
        msg.attach_alternative(body_html, "text/html")

        for filename, content, mimetype in _build_attachments(notif):
            msg.attach(filename, content, mimetype)

        msg.send()

        notif.is_emailed = True
        notif.emailed_at = timezone.now()
        notif.email_failure = ""
        notif.save(update_fields=["is_emailed", "emailed_at", "email_failure"])

        logger.info("Email sent to %s: %s", notif.user.email, subject)

    except Exception as exc:
        logger.exception(
            "Failed to send email for notification %s",
            notification_id,
        )
        # Store a truncated error so it can be inspected from the admin later
        notif.email_failure = str(exc)[:500]
        notif.save(update_fields=["email_failure"])

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)


@shared_task
def send_daily_digest():
    """
    Runs every morning. For each user with pending DIGEST notifications,
    send a single email that summarizes all of them.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()

    # Users who have at least one unsent digest notification
    users_with_digest = User.objects.filter(
        notifications__delivery_priority=DeliveryPriority.DIGEST,
        notifications__is_emailed=False,
    ).distinct()

    sent_count = 0
    for user in users_with_digest:
        try:
            if _send_user_digest(user):
                sent_count += 1
        except Exception as exc:
            # One user's failure must not stop the whole batch
            logger.error("Digest failed for %s: %s", user.email, exc)

    logger.info("Sent daily digest to %s users", sent_count)
    return sent_count


def _send_user_digest(user):
    """
    Send the digest email to one user.
    Returns True if an email was actually sent.
    """
    digest_notifs = list(
        Notification.objects.filter(
            user=user,
            delivery_priority=DeliveryPriority.DIGEST,
            is_emailed=False,
        ).order_by("-created_at")[
            :50
        ]  # Cap so one email cannot get huge
    )

    if not digest_notifs:
        return False

    notif_ids = [n.id for n in digest_notifs]

    # Respect the user's opt-out
    try:
        prefs = user.notification_preferences
        if not prefs.email_new_matches_digest:
            # Mark them as emailed so they are not reconsidered every morning
            Notification.objects.filter(id__in=notif_ids).update(is_emailed=True)
            logger.info("Digest skipped for %s — user opted out", user.email)
            return False
        unsubscribe_token = prefs.unsubscribe_token
    except NotificationPreferences.DoesNotExist:
        unsubscribe_token = ""

    # Group notifications by kind so the email can show them under headings
    grouped = {}
    for n in digest_notifs:
        grouped.setdefault(n.get_kind_display(), []).append(n)

    context = {
        "user": user,
        "user_name": getattr(user, "full_name", "") or user.email,
        "grouped_notifs": grouped,
        "total_count": len(digest_notifs),
        "frontend_url": settings.FRONTEND_URL,
        "support_email": settings.SUPPORT_EMAIL,
        "unsubscribe_url": (
            f"{settings.FRONTEND_URL}/unsubscribe/{unsubscribe_token}" if unsubscribe_token else ""
        ),
    }

    subject = render_to_string("emails/daily_digest/subject.txt", context).strip()
    body_text = render_to_string("emails/daily_digest/body.txt", context)
    body_html = render_to_string("emails/daily_digest/body.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    msg.attach_alternative(body_html, "text/html")
    msg.send()

    # Mark every included notification as emailed
    Notification.objects.filter(id__in=notif_ids).update(
        is_emailed=True,
        emailed_at=timezone.now(),
    )
    logger.info("Digest sent to %s (%s items)", user.email, len(digest_notifs))
    return True


@shared_task
def check_expiring_subscriptions():
    """
    Notify users whose subscription expires in 3 days.
    Runs once daily via Celery Beat.
    """
    from datetime import timedelta

    from apps.payments.models import Subscription

    target_date = timezone.now() + timedelta(days=3)

    expiring_subs = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        current_period_end__date=target_date.date(),
        auto_renew=False,  # Auto-renewing subscriptions do not need a warning
    )

    from .triggers import notify_subscription_expiring

    count = 0
    for sub in expiring_subs:
        try:
            notify_subscription_expiring(sub, days_remaining=3)
            count += 1
        except Exception as exc:
            # One bad row must not stop the whole run
            logger.error("Failed expiring notification for %s: %s", sub.id, exc)

    logger.info("Notified %s users about expiring subscriptions", count)
    return count
