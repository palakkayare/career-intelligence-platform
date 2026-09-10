from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import SoftDeleteModel, TimestampedModel
from apps.jobs.models import Job
from apps.seekers.models import SeekerProfile


class Application(TimestampedModel, SoftDeleteModel):
    """A seeker's application to a job."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REVIEWING = "reviewing", "Reviewing"
        SHORTLISTED = "shortlisted", "Shortlisted"
        INTERVIEW = "interview", "Interview"
        OFFERED = "offered", "Offered"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    seeker = models.ForeignKey(
        SeekerProfile,
        on_delete=models.PROTECT,  # Preserve history
        related_name="applications",
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.PROTECT,
        related_name="applications",
    )

    # Application content
    # Application content
    cover_letter = models.TextField(blank=True, max_length=2000)
    resume = models.ForeignKey(
        "resumes.Resume",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
        help_text="The uploaded resume sent with this application. Defaults "
        "to the seeker's primary resume at submission time.",
    )
    resume_url = models.URLField(
        blank=True,
        help_text="Optional external resume link (Drive, GitHub, personal "
        "site) for seekers who have not uploaded a file.",
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
        db_table = "applications"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["job", "status", "is_deleted"]),
            models.Index(fields=["seeker", "-submitted_at"]),
        ]
        constraints = [
            # A seeker may hold only one *active* application per job.
            # Withdrawn rows (is_deleted=True) fall outside the condition,
            # so a seeker can re-apply after withdrawing. This mirrors the
            # partial-constraint pattern used by Resume.one_primary_resume_per_user.
            models.UniqueConstraint(
                fields=["seeker", "job"],
                condition=models.Q(is_deleted=False),
                name="one_active_application_per_seeker_job",
            ),
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
        related_name="status_history",
    )
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="status_changes_made",
    )
    notes = models.TextField(blank=True, max_length=500)

    class Meta:
        db_table = "application_status_history"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.application_id}: {self.from_status} → {self.to_status}"
