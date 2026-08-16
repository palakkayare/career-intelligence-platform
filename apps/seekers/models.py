from django.conf import settings
from django.db import models
import uuid
from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.skills.models import Skill


class SeekerProfile(TimestampedModel, SoftDeleteModel):
    """
    Job seeker's profile. One per User (when role='seeker').
    """
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    class AvailabilityStatus(models.TextChoices):
        ACTIVELY_LOOKING = 'actively_looking', 'Actively Looking'
        OPEN_TO_OFFERS = 'open_to_offers', 'Open to Offers'
        NOT_LOOKING = 'not_looking', 'Not Looking'

    class Visibility(models.TextChoices):
        PUBLIC = 'public', 'Public'
        RECRUITERS_ONLY = 'recruiters_only', 'Recruiters Only'
        PRIVATE = 'private', 'Private'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='seeker_profile',
    )

    # Basic info
    
    full_name = models.CharField(max_length=255, blank=True)
    bio = models.TextField(blank=True, max_length=500)
    location = models.CharField(max_length=200, blank=True)
    profile_photo = models.ImageField(
        upload_to='profile_photos/%Y/%m/',
        null=True,
        blank=True,
    )

    # Career
    current_title = models.CharField(max_length=200, blank=True)
    target_role = models.CharField(max_length=200, blank=True)
    years_of_experience = models.PositiveSmallIntegerField(default=0)

    # Status & visibility
    availability_status = models.CharField(
        max_length=30,
        choices=AvailabilityStatus.choices,
        default=AvailabilityStatus.OPEN_TO_OFFERS,
    )
    visibility = models.CharField(
        max_length=30,
        choices=Visibility.choices,
        default=Visibility.RECRUITERS_ONLY,
    )

    # Portfolio links
    github_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    behance_url = models.URLField(blank=True)
    portfolio_url = models.URLField(blank=True)

    # Many-to-Many through SeekerSkill
    skills = models.ManyToManyField(
        Skill,
        through='SeekerSkill',
        related_name='seekers',
    )

    class Meta:
        db_table = 'seeker_profiles'

    def __str__(self):
        return f"{self.full_name or self.user.email} (seeker)"
    
class SeekerSkill(TimestampedModel):
    """
    Through model for SeekerProfile <-> Skill M2M.
    Stores proficiency level per user-skill.
    """

    class Proficiency(models.TextChoices):
        BEGINNER = 'beginner', 'Beginner'
        INTERMEDIATE = 'intermediate', 'Intermediate'
        ADVANCED = 'advanced', 'Advanced'
        EXPERT = 'expert', 'Expert'

    seeker = models.ForeignKey(
        SeekerProfile,
        on_delete=models.CASCADE,
        related_name='seeker_skills',
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name='seeker_skills',
    )
    proficiency = models.CharField(
        max_length=20,
        choices=Proficiency.choices,
        default=Proficiency.INTERMEDIATE,
    )
    years_of_experience = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'seeker_skills'
        unique_together = ('seeker', 'skill')  # One row per user-skill
        ordering = ['-proficiency', 'skill__name']

    def __str__(self):
        return f"{self.seeker.user.email} - {self.skill.name} ({self.proficiency})"
    
class WorkExperience(TimestampedModel, SoftDeleteModel):
    """One work experience entry per row."""

    class EmploymentType(models.TextChoices):
        FULL_TIME = 'full_time', 'Full Time'
        PART_TIME = 'part_time', 'Part Time'
        CONTRACT = 'contract', 'Contract'
        INTERNSHIP = 'internship', 'Internship'
        FREELANCE = 'freelance', 'Freelance'

    seeker = models.ForeignKey(
        SeekerProfile,
        on_delete=models.CASCADE,
        related_name='experiences',
    )
    company_name = models.CharField(max_length=255)
    job_title = models.CharField(max_length=255)
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.choices,
        default=EmploymentType.FULL_TIME,
    )
    location = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)  # null = currently working
    is_current = models.BooleanField(default=False)
    description = models.TextField(blank=True, max_length=2000)

    # Skills used in this role
    skills_used = models.ManyToManyField(Skill, blank=True, related_name='experiences')

    class Meta:
        db_table = 'work_experiences'
        ordering = ['-is_current', '-start_date']

    def __str__(self):
        return f"{self.job_title} @ {self.company_name}"


class Education(TimestampedModel, SoftDeleteModel):
    """Education entry."""

    class Degree(models.TextChoices):
        HIGH_SCHOOL = 'high_school', 'High School'
        DIPLOMA = 'diploma', 'Diploma'
        BACHELORS = 'bachelors', "Bachelor's"
        MASTERS = 'masters', "Master's"
        PHD = 'phd', 'PhD'
        OTHER = 'other', 'Other'

    seeker = models.ForeignKey(
        SeekerProfile,
        on_delete=models.CASCADE,
        related_name='educations',
    )
    institution_name = models.CharField(max_length=255)
    degree = models.CharField(max_length=20, choices=Degree.choices)
    field_of_study = models.CharField(max_length=255)
    start_year = models.PositiveSmallIntegerField()
    end_year = models.PositiveSmallIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=50, blank=True)  # "8.5 CGPA", "First Class"
    description = models.TextField(blank=True, max_length=1000)

    class Meta:
        db_table = 'educations'
        ordering = ['-end_year', '-start_year']

    def __str__(self):
        return f"{self.degree} in {self.field_of_study} - {self.institution_name}"