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

    # slugify() strips symbols, so "C", "C#" and "C++" all reduce to "c".
    # With a unique slug that means the second one cannot be saved at all.
    # These are spelled out rather than handled generically because the
    # replacement has to read well in a URL, and there are only a handful.
    SYMBOL_WORDS = (
        ('++', 'plusplus'),
        ('#', 'sharp'),
        ('.', 'dot'),
    )

    def _build_slug(self):
        """
        A slug that survives symbols.

        Falls back to appending a counter if two genuinely different names
        still collide - better a slug with a 2 on the end than a skill that
        cannot be created.
        """
        source = self.name
        for symbol, word in self.SYMBOL_WORDS:
            if symbol in source:
                source = source.replace(symbol, f' {word} ')

        base = slugify(source) or 'skill'
        slug = base

        counter = 2
        while (
            Skill.objects
            .filter(slug=slug)
            .exclude(pk=self.pk)
            .exists()
        ):
            slug = f'{base}-{counter}'
            counter += 1

        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._build_slug()
        super().save(*args, **kwargs)