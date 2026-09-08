from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class MatchScore(TimestampedModel):
    """
    Cached match score between a seeker and a job.
    Pre-computed by Celery Beat every 6 hours.
    """
    seeker = models.ForeignKey(
        'seekers.SeekerProfile',
        on_delete=models.CASCADE,
        related_name='match_scores',
    )
    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='match_scores',
    )

    # Component scores (0-100 each)
    overall_score = models.FloatField(db_index=True)
    skills_score = models.FloatField()
    experience_score = models.FloatField()
    location_score = models.FloatField()
    salary_score = models.FloatField()

    # Detail breakdown (JSON — used to power the explanation UI)
    breakdown = models.JSONField(default=dict, blank=True)

    # Tracking
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'match_scores'
        unique_together = ('seeker', 'job')
        indexes = [
            models.Index(fields=['seeker', '-overall_score']),
            models.Index(fields=['job', '-overall_score']),
            models.Index(fields=['-overall_score', '-computed_at']),
        ]

    def __str__(self):
        return f"{self.seeker.user.email} <-> {self.job.title} = {self.overall_score:.1f}"


class SavedCandidate(TimestampedModel):
    """Recruiter saves a seeker for later review."""
    recruiter = models.ForeignKey(
        'recruiters.RecruiterProfile',
        on_delete=models.CASCADE,
        related_name='saved_candidates',
    )
    seeker = models.ForeignKey(
        'seekers.SeekerProfile',
        on_delete=models.CASCADE,
        related_name='saved_by',
    )
    notes = models.TextField(blank=True, max_length=1000)

    class Meta:
        db_table = 'saved_candidates'
        unique_together = ('recruiter', 'seeker')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recruiter.full_name} saved {self.seeker.full_name}"