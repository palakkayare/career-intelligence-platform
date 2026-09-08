from rest_framework import serializers

from .models import Notification, NotificationPreferences


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only representation of a notification for the in-app list."""

    class Meta:
        model = Notification
        fields = (
            'id', 'kind', 'title', 'message', 'link',
            'is_read', 'read_at', 'created_at',
        )
        read_only_fields = fields


class NotificationPreferencesSerializer(serializers.ModelSerializer):
    """Editable email preferences. The unsubscribe token is never exposed."""

    class Meta:
        model = NotificationPreferences
        fields = (
            'email_application_updates',
            'email_new_matches_digest',
            'email_payment_events',
            'email_subscription_alerts',
            'email_profile_views',
            'email_marketing',
            'digest_hour',
        )