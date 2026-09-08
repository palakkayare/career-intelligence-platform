import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel, SoftDeleteModel


def resume_upload_path(instance, filename):
    """
    Generate S3 path: resumes/<user_id>/<uuid>.<ext>
    """
    ext = filename.split('.')[-1].lower()
    new_name = f"{uuid.uuid4()}.{ext}"
    return f"resumes/{instance.user.id}/{new_name}"


class Resume(TimestampedModel, SoftDeleteModel):
    """
    User's resume. Stored on S3, parsed by Celery + spaCy.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PARSING = 'parsing', 'Parsing'
        PARSED = 'parsed', 'Parsed'
        FAILED = 'failed', 'Failed'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='resumes',
    )
    name = models.CharField(
        max_length=200,
        help_text='User label (e.g., "Backend Developer Resume")',
    )
    file = models.FileField(upload_to=resume_upload_path)
    original_filename = models.CharField(max_length=255)
    file_size_bytes = models.PositiveIntegerField()
    is_primary = models.BooleanField(default=False)

    # Parsing status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # Parsed data (Step 17 mein populate hoga)
    extracted_text = models.TextField(blank=True)
    parsed_data = models.JSONField(default=dict, blank=True)

    # Diagnostics
    failure_reason = models.TextField(blank=True)
    parse_attempts = models.PositiveSmallIntegerField(default=0)
    parsed_at = models.DateTimeField(null=True, blank=True)
    extracted_skills = models.ManyToManyField(
        'skills.Skill',
        through='ResumeSkill',
        related_name='resumes',
    )
    ats_score = models.PositiveSmallIntegerField(null=True, blank=True)
    ats_breakdown = models.JSONField(default=dict, blank=True)
    
    advanced_ats_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Advanced ATS score, normalized to 0-100',
    )
    advanced_ats_breakdown = models.JSONField(default=dict, blank=True)
    advanced_ats_analyzed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'resumes'
        ordering = ['-is_primary', '-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_primary']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_primary=True, is_deleted=False),
                name='one_primary_resume_per_user',
            ),
        ]

    def __str__(self):
        primary = ' ⭐' if self.is_primary else ''
        return f"{self.name}{primary} ({self.user.email})"
        
class ResumeSkill(TimestampedModel):
    """
    Through model for Resume <-> Skill M2M.
    Tracks confidence score, extraction source, and confirmation status.
    """

    class Source(models.TextChoices):
        SKILLS_SECTION = 'skills_section', 'Skills Section'
        EXPERIENCE = 'experience', 'Experience Section'
        EDUCATION = 'education', 'Education Section'
        GENERAL = 'general', 'General Text'
        USER_ADDED = 'user_added', 'User Added'

    resume = models.ForeignKey(
        Resume,
        on_delete=models.CASCADE,
        related_name='resume_skills',
    )
    skill = models.ForeignKey(
        'skills.Skill',
        on_delete=models.CASCADE,
        related_name='resume_skills',
    )
    confidence = models.FloatField(default=0.5)  # Range: 0.0 - 1.0
    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.GENERAL,
    )
    mention_count = models.PositiveSmallIntegerField(default=1)
    is_confirmed = models.BooleanField(default=False)   # Manually verified by user
    is_user_added = models.BooleanField(default=False)  # Added by user, not extracted by AI

    class Meta:
        db_table = 'resume_skills'
        unique_together = ('resume', 'skill')
        ordering = ['-confidence', 'skill__name']

    def __str__(self):
        return f"{self.skill.name} ({self.confidence:.0%}) - {self.source}"