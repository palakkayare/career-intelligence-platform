import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimestampedModel
from apps.skills.models import Skill


class TargetRole(TimestampedModel):
    """
    Aspirational career roles.
    Curated by admins for now; ML-derived from real job data in Phase 4.
    """

    class Category(models.TextChoices):
        ENGINEERING = "engineering", "Engineering"
        DATA = "data", "Data & ML"
        DESIGN = "design", "Design"
        PRODUCT = "product", "Product"
        BUSINESS = "business", "Business"
        OPERATIONS = "operations", "Operations"
        OTHER = "other", "Other"

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.OTHER,
        db_index=True,
    )

    # Career stage hints
    min_experience_years = models.PositiveSmallIntegerField(default=0)
    typical_experience_years = models.PositiveSmallIntegerField(default=3)

    # Market data (manually seeded for now, ML-derived in Phase 4)
    avg_salary_inr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Annual salary in INR",
    )

    # Skills relationship
    skills = models.ManyToManyField(
        Skill,
        through="TargetRoleSkill",
        related_name="target_roles",
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "target_roles"
        ordering = ["sort_order", "name"]
        verbose_name = "Target Role"
        verbose_name_plural = "Target Roles"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class TargetRoleSkill(TimestampedModel):
    """
    Through model linking a role to a skill, with importance and
    learning-effort metadata attached.
    """

    class Importance(models.TextChoices):
        CRITICAL = "critical", "Critical (must have)"
        IMPORTANT = "important", "Important (strongly preferred)"
        PREFERRED = "preferred", "Preferred (bonus)"
        OPTIONAL = "optional", "Optional (nice to have)"

    class Difficulty(models.TextChoices):
        EASY = "easy", "Easy (1-2 weeks)"
        MEDIUM = "medium", "Medium (1-2 months)"
        HARD = "hard", "Hard (3+ months)"

    target_role = models.ForeignKey(
        TargetRole,
        on_delete=models.CASCADE,
        related_name="target_role_skills",
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name="target_role_skills",
    )

    importance = models.CharField(
        max_length=20,
        choices=Importance.choices,
        default=Importance.IMPORTANT,
    )
    difficulty = models.CharField(
        max_length=20,
        choices=Difficulty.choices,
        default=Difficulty.MEDIUM,
    )

    # Optional hint explaining why this skill matters for the role
    rationale = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "target_role_skills"
        unique_together = ("target_role", "skill")
        # NOTE: this is alphabetical, not semantic priority.
        # Real priority ordering happens in algorithm.py.
        ordering = ["-importance", "skill__name"]
        verbose_name = "Target Role Skill"
        verbose_name_plural = "Target Role Skills"
        indexes = [
            models.Index(
                fields=["target_role", "importance"],
                name="trs_role_importance_idx",
            ),
        ]

    def __str__(self):
        return f"{self.target_role.name} - {self.skill.name} [{self.importance}]"

    @property
    def importance_weight(self) -> float:
        """Numeric weight used by the gap scoring formula."""
        weights = {
            self.Importance.CRITICAL: 1.0,
            self.Importance.IMPORTANT: 0.7,
            self.Importance.PREFERRED: 0.4,
            self.Importance.OPTIONAL: 0.2,
        }
        return weights.get(self.importance, 0.5)


class SkillGapSnapshot(TimestampedModel):
    """
    Point-in-time capture of a seeker's gap against a target role.
    Used for tracking progress over time.
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    seeker = models.ForeignKey(
        "seekers.SeekerProfile",
        on_delete=models.CASCADE,
        related_name="skill_gap_snapshots",
    )
    target_role = models.ForeignKey(
        TargetRole,
        on_delete=models.PROTECT,
        related_name="snapshots",
    )

    # Score: 0 = perfect fit, 100 = full gap
    gap_score = models.FloatField(db_index=True)

    # Quick stats for list views and charts
    total_required_skills = models.PositiveSmallIntegerField()
    matched_count = models.PositiveSmallIntegerField()
    missing_critical_count = models.PositiveSmallIntegerField()
    missing_important_count = models.PositiveSmallIntegerField()

    # Detail payload so the frontend does not need extra DB queries
    # Shape: [{skill_id, skill_name, importance, difficulty, rationale}, ...]
    matched_skills = models.JSONField(default=list)
    missing_skills = models.JSONField(default=list)

    # Optional user-provided label, e.g. "January goal"
    label = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "skill_gap_snapshots"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["seeker", "-created_at"]),
            models.Index(fields=["seeker", "target_role", "-created_at"]),
        ]
        verbose_name = "Skill Gap Snapshot"
        verbose_name_plural = "Skill Gap Snapshots"

    def __str__(self):
        return f"{self.seeker.user.email} - {self.target_role.name} " f"= {self.gap_score}"


# ---------------------------------------------------------------------------
# Feature 13 - Learning Recommendations
# ---------------------------------------------------------------------------


class LearningProvider(TimestampedModel):
    """
    Platforms and publishers that host learning resources.
    Examples: Coursera, Udemy, edX, MDN, individual authors.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    # Visual
    logo_url = models.URLField(blank=True)
    website = models.URLField(blank=True)

    # Quality signal: official docs and universities rank higher than blogs
    trust_score = models.PositiveSmallIntegerField(
        default=5,
        help_text="0-10. Coursera/edX = 9, generic blog = 3",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "learning_providers"
        ordering = ["-trust_score", "name"]
        verbose_name = "Learning Provider"
        verbose_name_plural = "Learning Providers"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class LearningResource(TimestampedModel):
    """
    Any learnable resource: course, book, article, documentation, and so on.

    Kept generic on purpose - the recommendation engine does not care about
    the format, only about which skill the resource teaches and how good it is.
    """

    class Kind(models.TextChoices):
        COURSE = "course", "Video Course"
        BOOK = "book", "Book"
        ARTICLE = "article", "Article"
        DOCUMENTATION = "documentation", "Documentation"
        TUTORIAL = "tutorial", "Tutorial Series"
        BOOTCAMP = "bootcamp", "Bootcamp"
        PROJECT = "project", "Hands-on Project"
        CERTIFICATION = "certification", "Certification"
        VIDEO = "video", "Single Video"
        PODCAST = "podcast", "Podcast"

    class Difficulty(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"
        EXPERT = "expert", "Expert"

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, max_length=1000)
    url = models.URLField()

    kind = models.CharField(
        max_length=30,
        choices=Kind.choices,
        default=Kind.COURSE,
    )
    difficulty = models.CharField(
        max_length=20,
        choices=Difficulty.choices,
        default=Difficulty.BEGINNER,
    )

    # Practical details
    duration_hours = models.FloatField(
        null=True,
        blank=True,
        help_text="Approximate hours needed to complete",
    )
    is_free = models.BooleanField(default=False)
    price_inr = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Quality signals
    external_rating = models.FloatField(
        null=True,
        blank=True,
        help_text="Rating on the external platform (0-5)",
    )
    quality_score = models.PositiveSmallIntegerField(
        default=50,
        help_text="Internal computed score (0-100)",
    )

    provider = models.ForeignKey(
        LearningProvider,
        on_delete=models.PROTECT,
        related_name="resources",
        null=True,
        blank=True,
    )

    # Skills this resource teaches
    skills = models.ManyToManyField(
        Skill,
        through="ResourceSkill",
        related_name="learning_resources",
    )

    # Curation
    is_active = models.BooleanField(default=True)
    is_endorsed = models.BooleanField(
        default=False,
        help_text="Highly recommended by the curator",
    )

    # Tracking
    enrollment_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "learning_resources"
        ordering = ["-is_endorsed", "-quality_score", "title"]
        indexes = [
            models.Index(fields=["kind", "difficulty", "is_active"]),
            models.Index(fields=["-quality_score", "-is_endorsed"]),
        ]
        verbose_name = "Learning Resource"
        verbose_name_plural = "Learning Resources"

    def __str__(self):
        return f"{self.title} [{self.difficulty}]"


class ResourceSkill(TimestampedModel):
    """Through model: which skills does this resource teach, and how deeply?"""

    resource = models.ForeignKey(
        LearningResource,
        on_delete=models.CASCADE,
        related_name="resource_skills",
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name="resource_skills",
    )

    is_primary = models.BooleanField(
        default=False,
        help_text="Is this the main skill the resource teaches?",
    )
    coverage = models.PositiveSmallIntegerField(
        default=70,
        help_text="How thoroughly the skill is covered (0-100).",
    )

    class Meta:
        db_table = "resource_skills"
        unique_together = ("resource", "skill")
        ordering = ["-is_primary", "-coverage"]
        verbose_name = "Resource Skill"
        verbose_name_plural = "Resource Skills"

    def __str__(self):
        return f"{self.resource.title} - {self.skill.name}"


class UserLearning(TimestampedModel):
    """A user's interaction with a single learning resource."""

    class Status(models.TextChoices):
        WANT_TO_LEARN = "want_to_learn", "Want to Learn"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        DROPPED = "dropped", "Dropped"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learnings",
    )
    resource = models.ForeignKey(
        LearningResource,
        on_delete=models.PROTECT,
        related_name="user_learnings",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.WANT_TO_LEARN,
        db_index=True,
    )
    progress_pct = models.PositiveSmallIntegerField(
        default=0,
        help_text="Completion percentage (0-100)",
    )

    # Timeline
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # User feedback
    user_rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="The user's own rating, 1-5 stars",
    )
    notes = models.TextField(blank=True, max_length=1000)

    class Meta:
        db_table = "user_learnings"
        unique_together = ("user", "resource")
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]
        verbose_name = "User Learning"
        verbose_name_plural = "User Learnings"

    def __str__(self):
        return f"{self.user.email} - {self.resource.title} [{self.status}]"


# =============================================================================
# STEP 1 -- Append this to: apps/career_intel/models.py
#
# Required imports at the top of models.py (add only what is missing):
#     from django.conf import settings
#     from django.db import models
#     # TimestampedModel and TargetRole should already exist in this project.
# =============================================================================


class SalarySubmission(TimestampedModel):
    """
    A salary submission, published only in aggregate.

    The submitting user is stored internally so we can prevent duplicate
    entries and let people manage their own data, but the user is NEVER
    exposed through any aggregation endpoint.

    This makes a submission **pseudonymous, not anonymous** - deduplication
    requires linkability, and "one submission per person" and "truly
    anonymous" cannot both hold. DATA_PROTECTION.md gap 4 records the
    reasoning and the wording user-facing copy must use.
    """

    class CompanySizeBucket(models.TextChoices):
        STARTUP = "startup", "Startup (1-10)"
        SMALL = "small", "Small (11-50)"
        MEDIUM = "medium", "Medium (51-200)"
        LARGE = "large", "Large (201-1000)"
        ENTERPRISE = "enterprise", "Enterprise (1000+)"

    class ExperienceBucket(models.TextChoices):
        ENTRY = "0-2", "0-2 years"
        JUNIOR = "2-5", "2-5 years"
        MID = "5-10", "5-10 years"
        SENIOR = "10+", "10+ years"

    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full Time"
        CONTRACT = "contract", "Contract"
        INTERNSHIP = "internship", "Internship"
        FREELANCE = "freelance", "Freelance"

    class WorkArrangement(models.TextChoices):
        ON_SITE = "on_site", "On-site"
        HYBRID = "hybrid", "Hybrid"
        REMOTE = "remote", "Remote"

    # --- Internal tracking: used for de-duplication only, never exposed ---
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salary_submissions",
    )

    # --- Role ---
    role_title = models.CharField(
        max_length=200,
        db_index=True,
        help_text='For example: "Senior Backend Developer"',
    )
    target_role = models.ForeignKey(
        TargetRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salary_submissions",
    )

    # --- Context ---
    industry = models.ForeignKey(
        "industries.Industry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    location_city = models.CharField(max_length=100, db_index=True)
    company_size_bucket = models.CharField(
        max_length=20,
        choices=CompanySizeBucket.choices,
    )
    experience_years_bucket = models.CharField(
        max_length=10,
        choices=ExperienceBucket.choices,
    )
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

    # --- Compensation (INR, annual) ---
    salary_inr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Annual base salary in INR",
    )
    bonus_inr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Annual bonus or variable pay",
    )
    has_equity = models.BooleanField(
        default=False,
        help_text="Stock options or RSUs (yes/no only, the amount is not collected)",
    )

    # --- Trust and verification ---
    is_verified = models.BooleanField(default=False)
    is_flagged = models.BooleanField(
        default=False,
        help_text="Flagged by an admin as suspicious; excluded from all aggregates",
    )

    # --- Timeline ---
    effective_year = models.PositiveSmallIntegerField(
        help_text="The year this salary was effective",
    )
    # Keyed hash of the submitting IP, never the address itself. Used only
    # to rate-limit one device and to spot a single machine filling in a
    # whole city - it cannot be turned back into an address.
    submitter_ip_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "salary_submissions"
        ordering = ["-submitted_at"]
        indexes = [
            # Supports the main aggregation query path.
            models.Index(fields=["role_title", "location_city", "is_flagged"]),
            models.Index(fields=["target_role", "location_city"]),
            models.Index(fields=["effective_year"]),
        ]

    def __str__(self):
        return f"{self.role_title} ({self.location_city}, ₹{self.salary_inr / 100000:.1f}L)"


# =============================================================================
# STEP 2 -- Append this to: apps/career_intel/models.py
#
# Required imports at the top of models.py (add only what is missing):
#     from django.db import models
#     from django.utils.text import slugify
#     from apps.skills.models import Skill
#     # TimestampedModel and TargetRole should already exist in this project.
#
# NOTE: if models.py already imports Skill under a different path or alias,
# reuse that instead of adding a second import.
# =============================================================================


class CareerPathNode(TimestampedModel):
    """
    A single role in the career graph.

    Deliberately separate from TargetRole: graph nodes can be more granular
    and do not need a full skill mapping, which is TargetRole's job. A node
    may optionally link to a TargetRole when one exists.
    """

    class Level(models.IntegerChoices):
        ENTRY = 1, "Entry Level"
        JUNIOR = 2, "Junior"
        MID = 3, "Mid-level"
        SENIOR = 4, "Senior"
        LEAD = 5, "Lead/Principal"
        EXECUTIVE = 6, "Executive"

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True, max_length=1000)
    level = models.IntegerField(choices=Level.choices, default=Level.MID)
    category = models.CharField(
        max_length=30,
        choices=TargetRole.Category.choices,
        default=TargetRole.Category.OTHER,
    )

    # Optional link to an existing TargetRole, which carries the skill data.
    target_role = models.ForeignKey(
        TargetRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="career_nodes",
    )

    # Denormalised quick-reference values, copied from TargetRole when linked.
    typical_experience_years = models.PositiveSmallIntegerField(default=3)
    avg_salary_inr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "career_path_nodes"
        ordering = ["level", "name"]
        indexes = [
            models.Index(fields=["category", "level"]),
        ]

    def __str__(self):
        return f"{self.name} (L{self.level})"

    def save(self, *args, **kwargs):
        # Derive the slug from the name only when one was not supplied.
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class CareerPathEdge(TimestampedModel):
    """
    A directed edge representing one career transition.

    The edge carries everything the path-finder needs to score a route:
    an effort weight, a typical duration, and the skills the transition
    requires.
    """

    class TransitionType(models.TextChoices):
        VERTICAL = "vertical", "Vertical (promotion)"
        LATERAL = "lateral", "Lateral (same level)"
        LEAP = "leap", "Leap (skip levels)"
        PIVOT = "pivot", "Pivot (different category)"

    from_node = models.ForeignKey(
        CareerPathNode,
        on_delete=models.CASCADE,
        related_name="outgoing_edges",
    )
    to_node = models.ForeignKey(
        CareerPathNode,
        on_delete=models.CASCADE,
        related_name="incoming_edges",
    )

    # --- Cost of making this transition ---
    weight = models.PositiveSmallIntegerField(
        default=5,
        help_text="Difficulty: 1 = easy, 10 = very hard",
    )
    time_months = models.PositiveSmallIntegerField(
        default=12,
        help_text="Typical time needed to make this transition",
    )

    # --- Requirements ---
    required_skills = models.ManyToManyField(
        Skill,
        related_name="career_transitions",
        blank=True,
    )

    transition_type = models.CharField(
        max_length=20,
        choices=TransitionType.choices,
        default=TransitionType.VERTICAL,
    )

    rationale = models.TextField(
        blank=True,
        max_length=500,
        help_text="Why this is a common or valid transition",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "career_path_edges"
        # One edge per ordered pair; A->B and B->A are different rows.
        unique_together = ("from_node", "to_node")
        ordering = ["weight"]
        indexes = [
            models.Index(
                fields=["from_node", "weight"],
                name="cpe_from_weight_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.from_node.name} -> {self.to_node.name} "
            f"(w={self.weight}, {self.time_months}mo)"
        )
