"""
Badges, streaks, goals and points.

The tension worth naming up front: gamification exists for retention, and
points that unlock paid features work against revenue. The resolution here
is that points buy a narrow, short trial of one feature - enough to show
someone what they are missing, not enough to replace a subscription. The
earning rate is deliberately slow for the same reason.

The other rule: nothing here rewards volume for its own sake. A streak that
pays for applying to jobs you do not want makes the product worse for
seekers and worse for the recruiters reading those applications.
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class Badge(TimestampedModel):
    """
    Something a person earned once.

    Criteria are stored as a code the checker understands rather than as a
    rule engine. Six badge types do not justify an interpreter, and a
    hard-coded checker is far easier to reason about when someone asks why
    they did not get one.
    """

    class Category(models.TextChoices):
        PROFILE = "profile", "Profile"
        SKILLS = "skills", "Skills"
        APPLICATIONS = "applications", "Applications"
        LEARNING = "learning", "Learning"
        COMMUNITY = "community", "Community"

    code = models.SlugField(
        max_length=50,
        unique=True,
        help_text="Stable identifier the award checker matches on.",
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=250)
    category = models.CharField(max_length=20, choices=Category.choices)

    # What has to be true. Meaning depends on the code, e.g. a profile
    # strength floor or a number of applications.
    threshold = models.PositiveIntegerField(default=0)
    points = models.PositiveSmallIntegerField(
        default=10,
        help_text="Points awarded on earning this badge.",
    )
    icon = models.CharField(max_length=50, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "badges"
        ordering = ["category", "sort_order", "threshold"]

    def __str__(self):
        return self.name


class EarnedBadge(TimestampedModel):
    """A badge a specific person holds."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="badges",
    )
    badge = models.ForeignKey(
        Badge,
        on_delete=models.CASCADE,
        related_name="earned_by",
    )
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "earned_badges"
        ordering = ["-earned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "badge"],
                name="one_badge_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-earned_at"]),
        ]

    def __str__(self):
        return f"{self.user.email} earned {self.badge.code}"


class ApplicationStreak(TimestampedModel):
    """
    Consecutive weeks in which the seeker applied to at least one job.

    Weekly, not daily. A daily streak would push people to apply to
    something - anything - to avoid breaking it, which produces worse
    applications and wastes recruiters' time. A week is long enough that
    keeping the streak means actually job hunting.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="application_streak",
    )
    current_weeks = models.PositiveIntegerField(default=0)
    longest_weeks = models.PositiveIntegerField(default=0)
    # Monday of the last week that counted. Stored as a date so the
    # comparison is calendar-based rather than a rolling seven days.
    last_active_week = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "application_streaks"

    def __str__(self):
        return f"{self.user.email}: {self.current_weeks} weeks"


class WeeklyGoal(TimestampedModel):
    """
    A target the seeker set for one week.

    Self-set rather than assigned. A goal the platform picked is a quota;
    one the person picked is a commitment, and only the second changes
    behaviour.
    """

    class Kind(models.TextChoices):
        APPLICATIONS = "applications", "Applications sent"
        SKILLS_ADDED = "skills", "Skills added"
        COURSES_STARTED = "courses", "Courses started"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="weekly_goals",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    target = models.PositiveSmallIntegerField()
    week_start = models.DateField(help_text="Monday of the week this covers.")

    achieved_at = models.DateTimeField(null=True, blank=True)
    points_awarded = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "weekly_goals"
        ordering = ["-week_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind", "week_start"],
                name="one_goal_per_kind_per_week",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-week_start"]),
        ]

    def __str__(self):
        return f"{self.user.email}: {self.target} {self.kind} ({self.week_start})"


class PointsLedger(TimestampedModel):
    """
    Every points movement, in and out.

    A ledger rather than a balance column: when someone asks why they have
    47 points, the answer has to be reconstructable. A single mutable number
    cannot answer that, and quietly drifts.
    """

    class Reason(models.TextChoices):
        BADGE = "badge", "Badge earned"
        GOAL = "goal", "Weekly goal met"
        STREAK = "streak", "Streak milestone"
        REDEMPTION = "redemption", "Spent on a perk"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="points_entries",
    )
    # Negative for spending. Signed, so the balance is just a sum.
    delta = models.IntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    detail = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "points_ledger"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.user.email} {sign}{self.delta} ({self.reason})"


class PerkRedemption(TimestampedModel):
    """
    Points spent on a short trial of a paid feature.

    Deliberately narrow. The point is to show someone what a Pro feature
    does, not to hand them Pro for free - a points economy that substitutes
    for the subscription would cost more than the retention is worth.
    """

    class Perk(models.TextChoices):
        MATCH_SCORE_DAY = "match_score_day", "Match scores for 24 hours"
        SKILL_GAP_DAY = "skill_gap_day", "Skill gap report for 24 hours"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perk_redemptions",
    )
    perk = models.CharField(max_length=30, choices=Perk.choices)
    points_spent = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "perk_redemptions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "perk", "-expires_at"]),
        ]

    def __str__(self):
        return f"{self.user.email}: {self.perk} until {self.expires_at:%d %b}"

    def is_active(self):
        from django.utils import timezone

        return self.expires_at > timezone.now()
