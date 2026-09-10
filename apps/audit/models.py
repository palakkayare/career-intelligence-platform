"""
Audit trail.

Every create, update and delete on a registered model lands here, written
automatically by signals. The point is to be able to answer "who changed this
row, when, from what, to what, and from which IP" months after the fact -
which is both an operational need and a PDPB accountability requirement.
"""

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """One row per audited change. Append-only: never updated, never deleted."""

    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"

    # Who. Null covers system actions (Celery tasks, management commands) and
    # survives the actor's own account being removed.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    user_email = models.EmailField(
        blank=True,
        help_text="Copied at write time so the trail survives user deletion.",
    )

    # What
    action = models.CharField(max_length=10, choices=Action.choices, db_index=True)
    model_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="app_label.ModelName, e.g. jobs.Job",
    )
    object_id = models.CharField(max_length=64, db_index=True)
    object_repr = models.CharField(
        max_length=255,
        blank=True,
        help_text="str() of the object at write time, for readable listings.",
    )

    # Change detail. Only fields that actually differ are stored, so an update
    # touching one column does not persist the whole row twice.
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)

    # Request context
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]
        verbose_name = "Audit log entry"
        verbose_name_plural = "Audit log"

    def __str__(self):
        who = self.user_email or "system"
        return f"{who} {self.action} {self.model_name}#{self.object_id}"

    @property
    def changed_fields(self):
        """Field names touched by this entry."""
        return sorted(set(self.old_value) | set(self.new_value))
