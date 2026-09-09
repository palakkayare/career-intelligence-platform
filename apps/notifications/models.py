from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class NotificationKind(models.TextChoices):
    # Application events
    APPLICATION_RECEIVED = 'application_received', 'Application Received (Recruiter)'
    APPLICATION_STATUS_CHANGE = 'app_status_change', 'Application Status Changed (Seeker)'
    APPLICATION_WITHDRAWN = 'app_withdrawn', 'Application Withdrawn (Recruiter)'

    # Matching
    NEW_MATCHING_JOB = 'new_matching_job', 'New Matching Job (Seeker)'
    NEW_MATCHING_CANDIDATE = 'new_matching_candidate', 'New Matching Candidate (Recruiter)'

    # Payments
    PAYMENT_SUCCESS = 'payment_success', 'Payment Successful'
    PAYMENT_FAILED = 'payment_failed', 'Payment Failed'
    SUBSCRIPTION_EXPIRING = 'sub_expiring', 'Subscription Expiring Soon'
    SUBSCRIPTION_EXPIRED = 'sub_expired', 'Subscription Expired'

    # System
    RESUME_ANALYSIS_COMPLETE = 'resume_analysed', 'Resume Analysis Complete (Seeker)'
    PROFILE_VIEWED = 'profile_viewed', 'Profile Viewed (Seeker)'
    JOB_APPROVED = 'job_approved', 'Job Approved (Recruiter)'
    JOB_REJECTED = 'job_rejected', 'Job Rejected (Recruiter)'


class DeliveryPriority(models.TextChoices):
    INSTANT = 'instant', 'Instant'      # Email sent immediately via Celery
    DIGEST = 'digest', 'Daily Digest'   # Batched into the daily digest email
    NONE = 'none', 'In-App Only'        # Never emailed


class Notification(TimestampedModel):
    """
    A single notification event for a user.
    Can be in-app only, or also delivered via email.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    kind = models.CharField(
        max_length=50,
        choices=NotificationKind.choices,
        db_index=True,
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    link = models.CharField(max_length=500, blank=True)  # Deep link, e.g. /applications/me/12

    # Extra data used when rendering email templates
    context = models.JSONField(default=dict, blank=True)

    # Read state
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # Email delivery tracking
    delivery_priority = models.CharField(
        max_length=20,
        choices=DeliveryPriority.choices,
        default=DeliveryPriority.INSTANT,
    )
    is_emailed = models.BooleanField(default=False, db_index=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    email_failure = models.TextField(blank=True)  # Last error message, if sending failed

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            # Fast lookup for the user's notification list / unread count
            models.Index(fields=['user', 'is_read', '-created_at']),
            # Fast lookup for the daily digest task
            models.Index(fields=['delivery_priority', 'is_emailed']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.title}"


class NotificationPreferences(TimestampedModel):
    """User's email notification preferences."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preferences',
    )

    # Email opt-ins (default ON)
    email_application_updates = models.BooleanField(default=True)
    email_new_matches_digest = models.BooleanField(default=True)
    email_payment_events = models.BooleanField(default=True)
    email_subscription_alerts = models.BooleanField(default=True)

    # Low-value notification, default OFF
    email_profile_views = models.BooleanField(default=False)

    # Marketing (default OFF — opt-in required)
    email_marketing = models.BooleanField(default=False)

    # Digest delivery time (24-hour clock, user's local time)
    # Mobile push. Off by default: a device token only exists once the user
    # has installed the app and granted permission, and the switch should be
    # theirs to flip rather than something opt-out.
    push_enabled = models.BooleanField(default=False)

    digest_hour = models.PositiveSmallIntegerField(default=8)  # 8 AM

    # Token used in one-click unsubscribe links inside emails
    unsubscribe_token = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = 'notification_preferences'

    def __str__(self):
        return f"Prefs for {self.user.email}"

    def is_kind_enabled(self, kind):
        """Return True if the user wants email for this notification kind."""
        kind_map = {
            NotificationKind.APPLICATION_STATUS_CHANGE: 'email_application_updates',
            NotificationKind.APPLICATION_RECEIVED: 'email_application_updates',
            NotificationKind.APPLICATION_WITHDRAWN: 'email_application_updates',
            NotificationKind.NEW_MATCHING_JOB: 'email_new_matches_digest',
            NotificationKind.NEW_MATCHING_CANDIDATE: 'email_new_matches_digest',
            NotificationKind.PAYMENT_SUCCESS: 'email_payment_events',
            NotificationKind.PAYMENT_FAILED: 'email_payment_events',
            NotificationKind.SUBSCRIPTION_EXPIRING: 'email_subscription_alerts',
            NotificationKind.SUBSCRIPTION_EXPIRED: 'email_subscription_alerts',
            NotificationKind.RESUME_ANALYSIS_COMPLETE: 'email_application_updates',
            NotificationKind.PROFILE_VIEWED: 'email_profile_views',
            NotificationKind.JOB_APPROVED: 'email_application_updates',
            NotificationKind.JOB_REJECTED: 'email_application_updates',
        }
        attr = kind_map.get(kind)
        # Unknown kinds default to enabled
        return getattr(self, attr, True) if attr else True