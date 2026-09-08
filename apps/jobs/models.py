import uuid
from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.skills.models import Skill
from apps.recruiters.models import Company, RecruiterProfile
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField

class JobCategory(TimestampedModel):
    """
    Hierarchical job categories.
    e.g., Engineering > Backend Development
    """
    name = models.CharField(max_length=100, db_index=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='children',
    )
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)  # Frontend icon name
    sort_order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'job_categories'
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'Job Categories'
        unique_together = ('name', 'parent')  # Same name OK under different parents

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            if self.parent:
                self.slug = f"{self.parent.slug}-{base}"
            else:
                self.slug = base
        super().save(*args, **kwargs)
        
class Tag(TimestampedModel):
    """Free-form tags for jobs (admin-curated taxonomy)."""
    name = models.CharField(max_length=50, unique=True, db_index=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)  # Popularity tracking

    class Meta:
        db_table = 'job_tags'
        ordering = ['-use_count', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.name = self.name.lower().strip()
        super().save(*args, **kwargs)
        
class Job(TimestampedModel, SoftDeleteModel):
    """
    A job posting. Has a state machine for lifecycle management.
    """
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PENDING_APPROVAL = 'pending_approval', 'Pending Approval'
        ACTIVE = 'active', 'Active'
        CLOSED = 'closed', 'Closed'
        EXPIRED = 'expired', 'Expired'
        REJECTED = 'rejected', 'Rejected'

    class EmploymentType(models.TextChoices):
        FULL_TIME = 'full_time', 'Full Time'
        PART_TIME = 'part_time', 'Part Time'
        CONTRACT = 'contract', 'Contract'
        INTERNSHIP = 'internship', 'Internship'
        FREELANCE = 'freelance', 'Freelance'

    class WorkArrangement(models.TextChoices):
        ON_SITE = 'on_site', 'On-site'
        HYBRID = 'hybrid', 'Hybrid'
        REMOTE = 'remote', 'Remote'

    class SalaryPeriod(models.TextChoices):
        MONTHLY = 'monthly', 'Per Month'
        YEARLY = 'yearly', 'Per Year'

    # Public ID for shareable URLs (don't expose internal id)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # Basic info
    title = models.CharField(max_length=200, db_index=True)
    description = models.TextField(max_length=10000)

    # Posting context
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,  # Don't lose job if company is deleted
        related_name='jobs',
    )
    posted_by = models.ForeignKey(
        RecruiterProfile,
        on_delete=models.PROTECT,
        related_name='posted_jobs',
    )
    # Categorization
    category = models.ForeignKey(
        JobCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='jobs',
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='jobs')

    # Requirements
    required_skills = models.ManyToManyField(
        Skill,
        related_name='required_for_jobs',
    )
    nice_to_have_skills = models.ManyToManyField(
        Skill,
        related_name='nice_to_have_for_jobs',
        blank=True,
    )
    min_experience_years = models.PositiveSmallIntegerField(default=0)
    max_experience_years = models.PositiveSmallIntegerField(null=True, blank=True)

    # Type & arrangement
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.choices,
        default=EmploymentType.FULL_TIME,
    )
    work_arrangement = models.CharField(
        max_length=20,
        choices=WorkArrangement.choices,
        default=WorkArrangement.ON_SITE,
    )
    location = models.CharField(max_length=200, blank=True)

    # Compensation
    salary_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    salary_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    salary_currency = models.CharField(max_length=3, default='INR')
    salary_period = models.CharField(
        max_length=20,
        choices=SalaryPeriod.choices,
        default=SalaryPeriod.YEARLY,
    )
    is_salary_negotiable = models.BooleanField(default=False)
    is_salary_visible = models.BooleanField(default=True)  # Show in listings
    
    # Lifecycle
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    application_deadline = models.DateTimeField(null=True, blank=True)

    # Counters
    view_count = models.PositiveIntegerField(default=0)
    application_count = models.PositiveIntegerField(default=0)

    # Approval moderation
    rejection_reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Timeline tracking
    submitted_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Full-text search index
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        db_table = 'jobs'
        ordering = ['-activated_at', '-created_at']
        indexes = [
            models.Index(fields=['status', 'is_deleted', '-activated_at']),
            models.Index(fields=['company', 'status']),
            models.Index(fields=['category', 'status']),
            GinIndex(fields=['search_vector']),
        ]

    def __str__(self):
        return f"{self.title} @ {self.company.name} [{self.status}]"

    def is_publicly_visible(self):
        return self.status == self.Status.ACTIVE and not self.is_deleted

    def can_be_edited_by(self, user):
        """Editing rules: only draft/rejected by the recruiter who posted it."""
        if not hasattr(user, 'recruiter_profile'):
            return False
        if self.posted_by_id != user.recruiter_profile.id:
            return False
        return self.status in (self.Status.DRAFT, self.Status.REJECTED)
    
class SavedJob(TimestampedModel):
    """
    A job a seeker bookmarked to come back to.

    Kept separate from Application on purpose: saving is private and carries
    no signal to the recruiter, and a seeker can save a job, apply later, and
    still want the bookmark. Distinct from SavedSearch, which stores filters
    rather than a specific posting.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_jobs',
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name='saved_by',
    )
    note = models.CharField(
        max_length=500,
        blank=True,
        help_text="Seeker's private note. Never visible to the recruiter.",
    )

    class Meta:
        db_table = 'saved_jobs'
        ordering = ['-created_at']
        unique_together = ('user', 'job')
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.email} saved {self.job.title}"


class SavedSearch(TimestampedModel):
    """User can save filter combinations for quick re-use."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_searches',
    )
    name = models.CharField(max_length=100)
    query_text = models.CharField(max_length=500, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    notify_new_matches = models.BooleanField(default=False)  # Phase 2 use
    last_executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'saved_searches'
        ordering = ['-created_at']
        unique_together = ('user', 'name')

    def __str__(self):
        return f"{self.name} ({self.user.email})"


class SearchHistory(TimestampedModel):
    """Tracks user's recent searches. Auto-pruned to last 10."""
    MAX_PER_USER = 10

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='search_history',
    )
    query_text = models.CharField(max_length=500, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    result_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'search_history'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.query_text or '(filters only)'} - {self.result_count} results"