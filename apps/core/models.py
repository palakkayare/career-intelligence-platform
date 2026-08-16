"""
Base models for use across all apps.
Inherit these to get common functionality (timestamps, soft delete).
"""
from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    """
    Adds created_at and updated_at to any model.
    Almost every model in our system will extend this.
    """
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True  # Don't create a DB table for this model itself


class SoftDeleteManager(models.Manager):
    """
    Default manager that filters out soft-deleted rows.
    `Model.objects.all()` will not show deleted rows.
    """
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class SoftDeleteModel(models.Model):
    """
    Soft delete pattern: don't actually DELETE the row,
    just mark it as is_deleted=True. Preserves history.
    """
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()      # Default: only non-deleted rows
    all_objects = models.Manager()     # Includes deleted rows (for admin/restore)

    class Meta:
        abstract = True

    def soft_delete(self):
        """Mark this instance as deleted without removing it from the DB."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        """Reverse a soft delete (admin functionality)."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])