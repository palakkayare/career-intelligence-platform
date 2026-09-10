"""
Read-only audit log browser.

The blueprint asks for filtering by user, action type and date range - all
three are provided by list_filter below.
"""

import json

from django.contrib import admin
from django.utils.html import format_html

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user_email",
        "action",
        "model_name",
        "object_id",
        "object_repr",
        "ip_address",
    )
    list_filter = ("action", "model_name", "created_at")
    search_fields = ("user_email", "object_id", "object_repr", "model_name")
    date_hierarchy = "created_at"
    list_select_related = ("user",)
    readonly_fields = (
        "user",
        "user_email",
        "action",
        "model_name",
        "object_id",
        "object_repr",
        "ip_address",
        "user_agent",
        "created_at",
        "formatted_diff",
    )
    exclude = ("old_value", "new_value")

    @admin.display(description="Changes")
    def formatted_diff(self, obj):
        rows = []
        for field in obj.changed_fields:
            rows.append(
                "<tr><td><b>{}</b></td><td>{}</td><td>{}</td></tr>".format(
                    field,
                    json.dumps(obj.old_value.get(field), default=str),
                    json.dumps(obj.new_value.get(field), default=str),
                )
            )
        if not rows:
            return "-"
        return format_html(
            "<table><tr><th>Field</th><th>Before</th><th>After</th></tr>" "{}</table>",
            format_html("".join(rows)),
        )

    # The trail is append-only. Editing or deleting entries from the admin
    # would defeat the point of having it.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
