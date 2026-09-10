"""
Company reviews and interview experiences.

Two tensions shape everything here, and neither has a clean answer.

**Anonymous but verified.** Verification needs to know who wrote it;
anonymity needs not to. The resolution is that the author FK is stored and
never leaves the API - not in a serializer, not in an ordering, not in a
filter. That makes reviews pseudonymous rather than anonymous, which is
stated plainly in DATA_PROTECTION.md rather than papered over. The
alternative - storing no link at all - means one person can post fifty
reviews of a company that turned them down, and nobody can tell.

**Moderation.** Reviews publish immediately and are removed on report.
Pre-moderation sounds safer but review sections that queue for admin
approval sit empty, because nobody writes into a void for a week. The
protections are a per-company limit of one, an edit window, and a report
route that hides content pending review.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel

RATING_VALIDATORS = [MinValueValidator(1), MaxValueValidator(5)]


class CompanyReview(TimestampedModel, SoftDeleteModel):
    """
    One person's review of a company they worked at.

    Ratings are the four dimensions the blueprint names. Each is separate
    rather than one overall score, because "3 stars" tells a job seeker
    almost nothing while "great growth, poor management" tells them whether
    to apply.
    """

    class EmploymentStatus(models.TextChoices):
        CURRENT = "current", "Current employee"
        FORMER = "former", "Former employee"

    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        UNDER_REVIEW = "under_review", "Hidden pending review"
        REMOVED = "removed", "Removed by moderator"

    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    # Stored for verification, deduplication and abuse handling. Never
    # serialised. See the module docstring.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company_reviews",
    )

    job_title = models.CharField(max_length=120)
    employment_status = models.CharField(
        max_length=10,
        choices=EmploymentStatus.choices,
    )
    employment_years = models.PositiveSmallIntegerField(
        default=0,
        help_text="Years spent at the company.",
    )

    # The four dimensions from Feature 20
    rating_culture = models.PositiveSmallIntegerField(validators=RATING_VALIDATORS)
    rating_management = models.PositiveSmallIntegerField(validators=RATING_VALIDATORS)
    rating_growth = models.PositiveSmallIntegerField(validators=RATING_VALIDATORS)
    rating_salary = models.PositiveSmallIntegerField(validators=RATING_VALIDATORS)

    headline = models.CharField(max_length=150)
    # Both required. A review with only complaints or only praise is less
    # useful than one that admits the other side exists.
    pros = models.TextField(max_length=1500)
    cons = models.TextField(max_length=1500)
    advice_to_management = models.TextField(max_length=1000, blank=True)

    would_recommend = models.BooleanField(default=True)

    # True when the author has an application to this company on file. Weak
    # evidence, but better than nothing and honest about what it means.
    is_verified_employee = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PUBLISHED,
        db_index=True,
    )
    report_count = models.PositiveSmallIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "company_reviews"
        ordering = ["-created_at"]
        constraints = [
            # One review per person per company. Without it a single bad
            # experience can be posted twenty times.
            models.UniqueConstraint(
                fields=["company", "author"],
                condition=models.Q(is_deleted=False),
                name="one_review_per_person_per_company",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status", "-created_at"]),
            models.Index(fields=["status", "-helpful_count"]),
        ]

    def __str__(self):
        return f"{self.company.name}: {self.headline[:50]}"

    @property
    def overall_rating(self):
        """
        Mean of the four dimensions.

        Computed rather than stored: a stored average would need updating
        whenever any dimension changed, and there is nothing to gain from it
        at this scale.
        """
        total = (
            self.rating_culture + self.rating_management + self.rating_growth + self.rating_salary
        )
        return round(total / 4, 1)


class InterviewExperience(TimestampedModel, SoftDeleteModel):
    """
    An account of interviewing at a company.

    Separate from CompanyReview because the audience is different: someone
    with an interview next week wants process and questions, not what the
    canteen is like. Someone deciding whether to apply wants the reverse.
    """

    class Outcome(models.TextChoices):
        OFFER = "offer", "Received an offer"
        REJECTED = "rejected", "Rejected"
        WITHDREW = "withdrew", "Withdrew"
        PENDING = "pending", "Still waiting"

    class Difficulty(models.TextChoices):
        EASY = "easy", "Easy"
        MODERATE = "moderate", "Moderate"
        HARD = "hard", "Hard"

    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="interview_experiences",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="interview_experiences",
    )

    role_applied = models.CharField(max_length=120)
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    difficulty = models.CharField(max_length=10, choices=Difficulty.choices)
    rounds = models.PositiveSmallIntegerField(default=1)
    weeks_to_decision = models.PositiveSmallIntegerField(null=True, blank=True)

    process = models.TextField(
        max_length=2000,
        help_text="What the rounds were and how they ran.",
    )
    questions_asked = models.JSONField(
        default=list,
        blank=True,
        help_text="Questions remembered from the interview.",
    )

    was_experience_positive = models.BooleanField(default=True)

    status = models.CharField(
        max_length=20,
        choices=CompanyReview.Status.choices,
        default=CompanyReview.Status.PUBLISHED,
        db_index=True,
    )
    report_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "interview_experiences"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.company.name}: {self.role_applied} ({self.outcome})"


class CompanyResponse(TimestampedModel):
    """
    A company's public reply to a review.

    One per review, and only from a recruiter at that company. Letting a
    company reply repeatedly turns a review into an argument, which helps
    nobody reading it.
    """

    review = models.OneToOneField(
        CompanyReview,
        on_delete=models.CASCADE,
        related_name="company_response",
    )
    responder = models.ForeignKey(
        "recruiters.RecruiterProfile",
        on_delete=models.SET_NULL,
        null=True,
        related_name="review_responses",
    )
    # Kept so the response still reads correctly after the responder leaves.
    responder_name = models.CharField(max_length=120, blank=True)
    responder_title = models.CharField(max_length=120, blank=True)

    response = models.TextField(max_length=2000)

    class Meta:
        db_table = "company_review_responses"

    def __str__(self):
        return f"Response to {self.review_id}"


class ReviewReport(TimestampedModel):
    """
    Someone flagging a review.

    Reports hide content once a threshold is crossed rather than on the
    first click - otherwise a company could bury a fair review by having
    three people report it.
    """

    class Reason(models.TextChoices):
        FALSE = "false", "Factually untrue"
        ABUSIVE = "abusive", "Abusive or harassing"
        IDENTIFYING = "identifying", "Identifies an individual"
        SPAM = "spam", "Spam or promotional"
        OTHER = "other", "Something else"

    review = models.ForeignKey(
        CompanyReview,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_reports",
    )
    reason = models.CharField(max_length=20, choices=Reason.choices)
    detail = models.TextField(max_length=500, blank=True)

    reviewed_by_admin = models.BooleanField(default=False)
    admin_notes = models.TextField(max_length=500, blank=True)

    class Meta:
        db_table = "review_reports"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["review", "reported_by"],
                name="one_report_per_person_per_review",
            ),
        ]

    def __str__(self):
        return f"Report on {self.review_id}: {self.reason}"


class ReviewHelpfulVote(TimestampedModel):
    """
    A reader marking a review useful.

    Only useful, never unhelpful. A downvote button on a review of an
    employer is a tool for that employer, and the signal is not worth it.
    """

    review = models.ForeignKey(
        CompanyReview,
        on_delete=models.CASCADE,
        related_name="helpful_votes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="helpful_votes",
    )

    class Meta:
        db_table = "review_helpful_votes"
        constraints = [
            models.UniqueConstraint(
                fields=["review", "user"],
                name="one_helpful_vote_per_person",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} found {self.review_id} helpful"
