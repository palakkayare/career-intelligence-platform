from django.db import models
from django.utils.text import slugify

from apps.core.models import TimestampedModel


class SkillCategory(models.TextChoices):
    PROGRAMMING = 'programming', 'Programming Languages'
    FRAMEWORK = 'framework', 'Frameworks & Libraries'
    DATABASE = 'database', 'Databases'
    CLOUD = 'cloud', 'Cloud & DevOps'
    DESIGN = 'design', 'Design'
    SOFT_SKILL = 'soft_skill', 'Soft Skills'
    DOMAIN = 'domain', 'Domain Knowledge'
    TOOL = 'tool', 'Tools'
    OTHER = 'other', 'Other'


class Skill(TimestampedModel):
    """
    Master skill taxonomy — shared across all users and jobs.
    Admin manages additions, merges, deprecations.
    """
    name = models.CharField(max_length=100, unique=True, db_index=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    category = models.CharField(
        max_length=30,
        choices=SkillCategory.choices,
        default=SkillCategory.OTHER,
        db_index=True,
    )

    # Aliases for matching (e.g., "JS" → "JavaScript")
    aliases = models.JSONField(default=list, blank=True)

    # Admin moderation
    is_approved = models.BooleanField(default=True)
    is_deprecated = models.BooleanField(default=False)

    class Meta:
        db_table = 'skills'
        ordering = ['name']
        indexes = [
            models.Index(fields=['category', 'is_approved']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)