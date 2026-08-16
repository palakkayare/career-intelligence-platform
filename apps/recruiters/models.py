from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.industries.models import Industry


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