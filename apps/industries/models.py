from django.db import models
from django.utils.text import slugify

from apps.core.models import TimestampedModel


class Industry(TimestampedModel):
    """
    Master industry taxonomy. Companies link to this.
    """

    name = models.CharField(max_length=100, unique=True, db_index=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    aliases = models.JSONField(default=list, blank=True)

    # Display ordering
    sort_order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "industries"
        ordering = ["sort_order", "name"]
        verbose_name_plural = "Industries"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
