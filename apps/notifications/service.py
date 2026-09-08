"""
Centralized notification creation + delivery.
Every app should create notifications through this service, never directly.
"""
import logging

from django.utils import timezone

from .models import (
    Notification,
    NotificationPreferences,
    NotificationKind,
    DeliveryPriority,
)

logger = logging.getLogger(__name__)


# Maps each notification kind to how it should be delivered over email
KIND_PRIORITIES = {
    NotificationKind.APPLICATION_STATUS_CHANGE: DeliveryPriority.INSTANT,
    NotificationKind.APPLICATION_RECEIVED: DeliveryPriority.INSTANT,
    NotificationKind.APPLICATION_WITHDRAWN: DeliveryPriority.INSTANT,
    NotificationKind.NEW_MATCHING_JOB: DeliveryPriority.DIGEST,
    NotificationKind.NEW_MATCHING_CANDIDATE: DeliveryPriority.DIGEST,
    NotificationKind.PAYMENT_SUCCESS: DeliveryPriority.INSTANT,
    NotificationKind.PAYMENT_FAILED: DeliveryPriority.INSTANT,
    NotificationKind.SUBSCRIPTION_EXPIRING: DeliveryPriority.INSTANT,
    NotificationKind.SUBSCRIPTION_EXPIRED: DeliveryPriority.INSTANT,
    NotificationKind.PROFILE_VIEWED: DeliveryPriority.NONE,  # In-app only
    NotificationKind.JOB_APPROVED: DeliveryPriority.INSTANT,
    NotificationKind.JOB_REJECTED: DeliveryPriority.INSTANT,
}


class NotificationService:
    """Single entry point for creating and reading notifications."""

    @classmethod
    def create(cls, user, kind, title, message, link='', context=None):
        """
        Create a notification.

        - Always saves a Notification row, so it shows up in-app immediately
        - Queues an email only if priority is INSTANT and the user opted in
        """
        priority = KIND_PRIORITIES.get(kind, DeliveryPriority.INSTANT)

        notif = Notification.objects.create(
            user=user,
            kind=kind,
            title=title,
            message=message,
            link=link,
            context=context or {},
            delivery_priority=priority,
        )

        # Digest notifications are picked up later by the daily Beat task
        if priority == DeliveryPriority.INSTANT:
            cls._maybe_send_email(notif)
            cls.push_notification(notif)

        return notif

    @classmethod
    def push_notification(cls, notif):
        """
        Mobile push delivery. Stub until the app ships.

        Everything around the send is real - the device token, the opt-in
        preference, the decision about which notifications are push-worthy -
        so the only thing left when Firebase is wired up is the call itself.
        Keeping the decision logic here rather than deferring all of it means
        the token and preference plumbing gets exercised now instead of being
        discovered broken on launch day.

        Returns True when a push would have been sent.
        """
        user = notif.user

        token = getattr(user, 'fcm_token', None)
        if not token:
            return False

        try:
            prefs = user.notification_preferences
        except NotificationPreferences.DoesNotExist:
            return False

        if not prefs.push_enabled:
            return False

        # TODO: replace with a Firebase Admin SDK send once the mobile app
        # exists. Expected shape:
        #     messaging.send(messaging.Message(
        #         token=token,
        #         notification=messaging.Notification(
        #             title=notif.title, body=notif.message,
        #         ),
        #         data={'link': notif.link, 'kind': notif.kind},
        #     ))
        logger.info(
            'Push notification queued (stub) for %s: %s',
            user.email, notif.title,
        )
        return True

    @classmethod
    def _maybe_send_email(cls, notif):
        """Check the user's preferences, then queue the Celery email task."""
        try:
            prefs = notif.user.notification_preferences
        except NotificationPreferences.DoesNotExist:
            # No preferences row means the user is treated as opted in
            prefs = None

        if prefs and not prefs.is_kind_enabled(notif.kind):
            logger.info(
                "Email skipped for %s (%s) — user opted out",
                notif.user.email, notif.kind,
            )
            return

        # Imported here to avoid a circular import between service and tasks
        from django.db import transaction
        from .tasks import send_notification_email

        # Queue the email only after the surrounding DB transaction commits,
        # so the worker never looks for a row that is not yet visible
        transaction.on_commit(lambda: send_notification_email.delay(notif.id))

    @classmethod
    def mark_read(cls, notification, user):
        """Mark a single notification as read. Raises if it is not the user's own."""
        if notification.user_id != user.id:
            raise PermissionError("Not your notification")

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])

    @classmethod
    def mark_all_read(cls, user):
        """Bulk mark every unread notification of this user as read."""
        Notification.objects.filter(
            user=user,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now())

    @classmethod
    def unread_count(cls, user):
        """Return how many unread notifications the user has."""
        return Notification.objects.filter(user=user, is_read=False).count()