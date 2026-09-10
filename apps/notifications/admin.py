from django.contrib import admin

from .models import Notification, NotificationPreferences


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "kind",
        "title_short",
        "is_read",
        "is_emailed",
        "delivery_priority",
        "created_at",
    )
    list_filter = ("kind", "is_read", "is_emailed", "delivery_priority")
    search_fields = ("user__email", "title", "message")
    raw_id_fields = ("user",)
    # Notifications are an audit trail — they are created by code, never edited
    readonly_fields = (
        "user",
        "kind",
        "title",
        "message",
        "link",
        "context",
        "delivery_priority",
        "is_read",
        "read_at",
        "is_emailed",
        "emailed_at",
        "email_failure",
        "created_at",
    )
    actions = ["retry_email_send"]

    def get_queryset(self, request):
        # Avoids one extra query per row for the user column
        return super().get_queryset(request).select_related("user")

    @admin.display(description="Title")
    def title_short(self, obj):
        return obj.title[:50] + "..." if len(obj.title) > 50 else obj.title

    @admin.action(description="Retry email send for selected")
    def retry_email_send(self, request, queryset):
        """Re-queue emails that failed, for example during a SendGrid outage."""
        from .tasks import send_notification_email

        count = 0
        for notif in queryset.filter(is_emailed=False):
            send_notification_email.delay(notif.id)
            count += 1

        self.message_user(request, f"Re-queued {count} email(s).")


@admin.register(NotificationPreferences)
class NotificationPreferencesAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "email_application_updates",
        "email_new_matches_digest",
        "email_payment_events",
        "email_marketing",
    )
    list_filter = (
        "email_application_updates",
        "email_new_matches_digest",
        "email_payment_events",
        "email_marketing",
    )
    search_fields = ("user__email",)
    raw_id_fields = ("user",)
    # The token is a secret used in public unsubscribe links
    readonly_fields = ("unsubscribe_token",)
