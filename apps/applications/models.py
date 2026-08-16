from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.jobs.models import Job
from apps.seekers.models import SeekerProfile


class Application(TimestampedModel, SoftDeleteModel):
    """A seeker's application to a job."""

    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'Submitted'
        REVIEWING = 'reviewing', 'Reviewing'
        SHORTLISTED = 'shortlisted', 'Shortlisted'
        INTERVIEW = 'interview', 'Interview'
        OFFERED = 'offered', 'Offered'
        REJECTED = 'rejected', 'Rejected'
        WITHDRAWN = 'withdrawn', 'Withdrawn'

    seeker = models.ForeignKey(
        SeekerProfile,
        on_delete=models.PROTECT,  # Preserve history
        related_name='applications',
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.PROTECT,
        related_name='applications',
    )

    # Application content
    cover_letter = models.TextField(blank=True, max_length=2000)
    resume_url = models.URLField(
        blank=True,
        help_text='Link to online resume (Drive, GitHub, etc.). '
                   'Phase 2 mein resume upload aayega.',
    )

    # Status workflow
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUBMITTED,
        db_index=True,
    )

    # Recruiter private notes (not visible to seeker)
    recruiter_notes = models.TextField(blank=True, max_length=2000)

    # Tracking
    submitted_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_status_change_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'applications'
        ordering = ['-submitted_at']
        unique_together = ('seeker', 'job')  # One application per user per job
        indexes = [
            models.Index(fields=['job', 'status', 'is_deleted']),
            models.Index(fields=['seeker', '-submitted_at']),
        ]

    def __str__(self):
        return f"{self.seeker.user.email} → {self.job.title} [{self.status}]"

    @property
    def is_terminal(self):
        return self.status in (
            self.Status.OFFERED,
            self.Status.REJECTED,
            self.Status.WITHDRAWN,
        )


class ApplicationStatusHistory(TimestampedModel):
    """Audit trail for application status changes."""

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,  # If application gone, history irrelevant
        related_name='status_history',
    )
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='status_changes_made',
    )
    notes = models.TextField(blank=True, max_length=500)

    class Meta:
        db_table = 'application_status_history'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.application_id}: {self.from_status} → {self.to_status}"