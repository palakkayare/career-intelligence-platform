from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.industries.models import Industry
from datetime import date, timedelta
class Company(TimestampedModel, SoftDeleteModel):
    """
    A company entity. Recruiters belong to a company.
    """

    class Size(models.TextChoices):
        STARTUP = 'startup', '1-10 employees'
        SMALL = 'small', '11-50 employees'
        MEDIUM = 'medium', '51-200 employees'
        LARGE = 'large', '201-1000 employees'
        ENTERPRISE = 'enterprise', '1000+ employees'

    name = models.CharField(max_length=255, unique=True, db_index=True)
    slug = models.SlugField(max_length=280, unique=True, blank=True)

    # Branding
    logo = models.ImageField(
        upload_to='company_logos/%Y/%m/',
        null=True,
        blank=True,
    )
    description = models.TextField(blank=True, max_length=2000)
    culture_statement = models.TextField(blank=True, max_length=1000)

    # Details
    industry = models.ForeignKey(
        Industry,
        on_delete=models.PROTECT,
        related_name='companies',
        null=True,
        blank=True,
    )
    size = models.CharField(max_length=20, choices=Size.choices, blank=True)
    founded_year = models.PositiveSmallIntegerField(null=True, blank=True)
    website = models.URLField(blank=True)
    headquarters_location = models.CharField(max_length=200, blank=True)

    # Verification (admin-controlled)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_notes = models.TextField(blank=True)

    # Tracking
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='companies_created',
    )

    class Meta:
        db_table = 'companies'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_verified', 'is_deleted']),
            models.Index(fields=['industry', 'is_verified']),
        ]
        verbose_name_plural = 'Companies'

    def __str__(self):
        verified = ' ✓' if self.is_verified else ''
        return f"{self.name}{verified}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def verify(self, notes=''):
        """Admin action — mark verified."""
        from django.utils import timezone
        self.is_verified = True
        self.verified_at = timezone.now()
        if notes:
            self.verification_notes = notes
        self.save(update_fields=['is_verified', 'verified_at', 'verification_notes'])

class RecruiterProfile(TimestampedModel, SoftDeleteModel):
    """
    Recruiter's profile. One per User (when role='recruiter').
    Linked to a Company.
    """

    class ContactVisibility(models.TextChoices):
        PUBLIC = 'public', 'Public'
        CONNECTED = 'connected', 'Connected (Applied Candidates Only)'
        PRIVATE = 'private', 'Private'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recruiter_profile',
    )

    # Company link
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recruiters',
    )
    is_company_admin = models.BooleanField(
        default=False,
        help_text="Can edit company info and manage team",
    )

    # Personal info
    full_name = models.CharField(max_length=255, blank=True)
    position = models.CharField(
        max_length=200,
        blank=True,
        help_text="e.g., 'Senior Talent Acquisition Manager'",
    )
    bio = models.TextField(blank=True, max_length=500)
    profile_photo = models.ImageField(
        upload_to='recruiter_photos/%Y/%m/',
        null=True,
        blank=True,
    )

    # Contact
    phone = models.CharField(max_length=20, blank=True)
    linkedin_url = models.URLField(blank=True)
    contact_visibility = models.CharField(
        max_length=20,
        choices=ContactVisibility.choices,
        default=ContactVisibility.CONNECTED,
    )

    class Meta:
        db_table = 'recruiter_profiles'
        indexes = [
            models.Index(fields=['company', 'is_company_admin']),
        ]

    def __str__(self):
        company_str = self.company.name if self.company else 'No Company'
        return f"{self.full_name or self.user.email} ({company_str})"

    def can_edit_company(self):
        """Only company admins can edit company info."""
        return self.is_company_admin and self.company_id is not None
    
class RecruiterCredits(TimestampedModel):
    """
    Monthly contact-reveal credits for a recruiter.
    The cycle is reset by a daily Celery Beat task, with a lazy
    fallback reset whenever the balance is read or spent.
    """

    recruiter = models.OneToOneField(
        'recruiters.RecruiterProfile',
        on_delete=models.CASCADE,
        related_name='credits',
    )

    # Allocation — synced from the plan on subscription activation
    monthly_reveal_limit = models.PositiveSmallIntegerField(default=0)
    reveals_used_this_month = models.PositiveSmallIntegerField(default=0)

    # Cycle tracking
    cycle_starts_on = models.DateField(default=date.today)

    class Meta:
        db_table = 'recruiter_credits'
        verbose_name_plural = 'Recruiter credits'

    def __str__(self):
        return (
            f'{self.recruiter.full_name}: '
            f'{self.reveals_used_this_month}/{self.monthly_reveal_limit}'
        )

    @property
    def remaining(self):
        """Credits left in the current cycle. Never negative."""
        return max(0, self.monthly_reveal_limit - self.reveals_used_this_month)

    @property
    def cycle_ends_on(self):
        return self.cycle_starts_on + timedelta(days=30)

    def is_cycle_expired(self):
        return date.today() >= self.cycle_ends_on

    def reset_cycle(self):
        """Start a fresh 30-day cycle with a zeroed counter."""
        self.reveals_used_this_month = 0
        self.cycle_starts_on = date.today()
        self.save(update_fields=['reveals_used_this_month', 'cycle_starts_on'])


class CandidateView(TimestampedModel):
    """
    Audit trail: every time a recruiter sees a seeker profile.
    Used for seeker notifications, recruiter analytics and GDPR compliance.
    """

    class ViewKind(models.TextChoices):
        SEARCH_RESULT = 'search_result', 'Search Result'
        DETAIL = 'detail', 'Detail View'
        SAVED_LIST = 'saved_list', 'Saved Candidates List'

    recruiter = models.ForeignKey(
        'recruiters.RecruiterProfile',
        on_delete=models.CASCADE,
        related_name='candidate_views',
    )
    seeker = models.ForeignKey(
        'seekers.SeekerProfile',
        on_delete=models.CASCADE,
        related_name='profile_views',
    )
    view_kind = models.CharField(max_length=20, choices=ViewKind.choices)

    # Contact reveal tracking
    contact_revealed = models.BooleanField(default=False)
    revealed_at = models.DateTimeField(null=True, blank=True)

    # Optional context: which job the recruiter was hiring for
    target_job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='candidate_views',
        help_text='Job the recruiter was searching for, if any',
    )

    class Meta:
        db_table = 'candidate_views'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recruiter', '-created_at']),
            models.Index(fields=['seeker', '-created_at']),
            models.Index(fields=['contact_revealed', '-revealed_at']),
            # Speeds up the "was this contact already revealed?" check
            models.Index(fields=['recruiter', 'seeker', 'contact_revealed']),
        ]

    def __str__(self):
        return (
            f'{self.recruiter.full_name} viewed '
            f'{self.seeker.user.email} ({self.view_kind})'
        )


class TalentPool(TimestampedModel):
    """
    A saved candidate search that stays current.

    The distinction from SavedCandidate matters: that is a manual list of
    people a recruiter picked, this is a set of criteria. A pool for "Python,
    Bangalore, 5+ years" gains members as seekers sign up, without anyone
    revisiting it - which is the "auto-update" the blueprint asks for
    (Feature 15).

    Only the filters are stored. Results are computed on read, so a pool can
    never go stale or hold on to a seeker who has since gone private.
    """
    recruiter = models.ForeignKey(
        'RecruiterProfile',
        on_delete=models.CASCADE,
        related_name='talent_pools',
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)

    # Same shape CandidateSearchService already accepts, so a recruiter can
    # save the search they just ran without translating anything.
    filters = models.JSONField(default=dict, blank=True)

    notify_on_new = models.BooleanField(
        default=True,
        help_text='Email the recruiter when new candidates enter this pool.',
    )
    # Everything newer than this is "new" on the next sweep. Not a cache of
    # results - just a marker of how far the last notification got.
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'talent_pools'
        ordering = ['-created_at']
        unique_together = ('recruiter', 'name')
        indexes = [
            models.Index(fields=['recruiter', '-created_at']),
        ]

    def __str__(self):
        return f'{self.name} ({self.recruiter.full_name})'