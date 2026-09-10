"""
Gamification services.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import ApplicationStreak, Badge, EarnedBadge, PerkRedemption, PointsLedger, WeeklyGoal

logger = logging.getLogger(__name__)

# What a perk costs and how long it lasts. Priced so that reaching one takes
# real engagement - roughly a month of steady use - rather than an afternoon.
PERK_COSTS = {
    PerkRedemption.Perk.MATCH_SCORE_DAY: 100,
    PerkRedemption.Perk.SKILL_GAP_DAY: 150,
}
PERK_DURATION_HOURS = 24

STREAK_MILESTONES = {4: 25, 12: 75, 26: 200}


def week_start(when=None):
    """Monday of the week containing `when`. The unit everything here uses."""
    day = (when or timezone.now()).date()
    return day - timedelta(days=day.weekday())


class PointsService:
    """The ledger. Balance is always a sum, never a stored number."""

    @classmethod
    def balance(cls, user):
        return (
            PointsLedger.objects.filter(user=user).aggregate(
                total=Sum("delta"),
            )["total"]
            or 0
        )

    @classmethod
    def award(cls, user, amount, reason, detail=""):
        """
        Add points. Refuses zero or negative amounts - spending goes through
        `spend`, so a bug cannot quietly hand someone a negative award.
        """
        if amount <= 0:
            raise ValidationError({"detail": "Award amount must be positive."})

        return PointsLedger.objects.create(
            user=user,
            delta=amount,
            reason=reason,
            detail=detail,
        )

    @classmethod
    @transaction.atomic
    def spend(cls, user, amount, reason, detail=""):
        """
        Deduct points, refusing to go below zero.

        The balance is recomputed inside the transaction rather than trusted
        from an earlier read, so two concurrent redemptions cannot both pass
        the check.
        """
        if amount <= 0:
            raise ValidationError({"detail": "Spend amount must be positive."})

        current = (
            PointsLedger.objects.select_for_update()
            .filter(
                user=user,
            )
            .aggregate(total=Sum("delta"))["total"]
            or 0
        )

        if current < amount:
            raise ValidationError(
                {
                    "detail": f"Not enough points. You have {current}, " f"this costs {amount}.",
                }
            )

        return PointsLedger.objects.create(
            user=user,
            delta=-amount,
            reason=reason,
            detail=detail,
        )

    @classmethod
    def history(cls, user, limit=50):
        return PointsLedger.objects.filter(user=user)[:limit]


class BadgeService:
    """Awarding badges."""

    @classmethod
    def award(cls, user, badge_code):
        """
        Give a badge if it is not already held. Idempotent.

        Points come with the badge, and only on the first award - which is
        what the unique constraint guarantees.
        """
        badge = Badge.objects.filter(code=badge_code, is_active=True).first()
        if badge is None:
            return None, False

        earned, created = EarnedBadge.objects.get_or_create(
            user=user,
            badge=badge,
        )

        if created and badge.points:
            PointsService.award(
                user,
                badge.points,
                PointsLedger.Reason.BADGE,
                detail=badge.name,
            )

        return earned, created

    @classmethod
    def check_all(cls, user):
        """
        Re-evaluate every badge for one user.

        Runs on demand rather than on every save. Checking six criteria on
        each profile edit would mean six extra queries on the hot path for a
        badge that changes once.
        """
        newly_earned = []

        for code in cls._qualifying_codes(user):
            _, created = cls.award(user, code)
            if created:
                newly_earned.append(code)

        return newly_earned

    @classmethod
    def _qualifying_codes(cls, user):
        """
        Which badges this user currently meets the criteria for.

        Hard-coded per code rather than a rule engine. Six badges do not
        justify an interpreter, and this version can be read.
        """
        from apps.applications.models import Application

        codes = []
        profile = getattr(user, "seeker_profile", None)
        if profile is None:
            return codes

        strength = profile.profile_strength
        for code, floor in (
            ("profile-started", 25),
            ("profile-half", 50),
            ("profile-complete", 100),
        ):
            if strength >= floor:
                codes.append(code)

        skill_count = profile.seeker_skills.count()
        for code, floor in (("skills-5", 5), ("skills-10", 10)):
            if skill_count >= floor:
                codes.append(code)

        # all_objects: a withdrawn application was still an application. The
        # badge marks the act of applying, not the outcome.
        application_count = Application.all_objects.filter(seeker=profile).count()
        for code, floor in (
            ("first-application", 1),
            ("applications-10", 10),
            ("applications-25", 25),
        ):
            if application_count >= floor:
                codes.append(code)

        return codes


class StreakService:
    """
    Weekly application streaks.

    Weekly rather than daily on purpose: a daily streak rewards applying to
    something every day, which produces worse applications and wastes the
    recruiter's time on the other end.
    """

    @classmethod
    def record_application(cls, user, when=None):
        """
        Called when an application is submitted. Idempotent within a week -
        the tenth application of the week does not extend anything.
        """
        this_week = week_start(when)
        streak, _ = ApplicationStreak.objects.get_or_create(user=user)

        if streak.last_active_week == this_week:
            return streak

        if streak.last_active_week == this_week - timedelta(days=7):
            streak.current_weeks += 1
        else:
            # Either the first week ever, or the chain is broken. Both start
            # a new streak at one rather than zero - this week counted.
            streak.current_weeks = 1

        streak.last_active_week = this_week
        streak.longest_weeks = max(streak.longest_weeks, streak.current_weeks)
        streak.save()

        cls._award_milestone(user, streak.current_weeks)
        return streak

    @classmethod
    def _award_milestone(cls, user, weeks):
        points = STREAK_MILESTONES.get(weeks)
        if points:
            PointsService.award(
                user,
                points,
                PointsLedger.Reason.STREAK,
                detail=f"{weeks}-week application streak",
            )

    @classmethod
    def current(cls, user):
        """
        The live streak, accounting for time passing.

        The stored number is only correct until a week goes by without an
        application. Reading it raw would show a streak that ended a month
        ago, so the gap is checked on read rather than by a nightly job.
        """
        streak = ApplicationStreak.objects.filter(user=user).first()
        if streak is None or streak.last_active_week is None:
            return {"current_weeks": 0, "longest_weeks": 0, "is_live": False}

        this_week = week_start()
        gap = (this_week - streak.last_active_week).days // 7

        # 0 means they applied this week, 1 means last week and the streak
        # is still alive until this week ends.
        is_live = gap <= 1

        return {
            "current_weeks": streak.current_weeks if is_live else 0,
            "longest_weeks": streak.longest_weeks,
            "is_live": is_live,
            "last_active_week": streak.last_active_week,
        }


class GoalService:
    """Weekly goals the seeker sets for themselves."""

    GOAL_POINTS = 20
    MAX_TARGET = 50

    @classmethod
    def set_goal(cls, user, kind, target, when=None):
        """
        Set or update this week's goal for one kind.

        Updating is allowed while the week is open. Locking it would push
        people to set a low target they know they will hit, which is the
        opposite of useful.
        """
        if target < 1 or target > cls.MAX_TARGET:
            raise ValidationError(
                {
                    "target": f"Pick a target between 1 and {cls.MAX_TARGET}.",
                }
            )

        goal, _ = WeeklyGoal.objects.update_or_create(
            user=user,
            kind=kind,
            week_start=week_start(when),
            defaults={"target": target},
        )
        return goal

    @classmethod
    def progress(cls, user, when=None):
        """This week's goals with live counts against them."""
        start = week_start(when)
        goals = WeeklyGoal.objects.filter(user=user, week_start=start)

        return [
            {
                "id": goal.id,
                "kind": goal.kind,
                "label": goal.get_kind_display(),
                "target": goal.target,
                "current": cls._count(user, goal.kind, start),
                "achieved": goal.achieved_at is not None,
            }
            for goal in goals
        ]

    @classmethod
    def _count(cls, user, kind, start):
        from apps.applications.models import Application
        from apps.career_intel.models import UserLearning
        from apps.seekers.models import SeekerSkill

        profile = getattr(user, "seeker_profile", None)
        if profile is None:
            return 0

        if kind == WeeklyGoal.Kind.APPLICATIONS:
            return Application.all_objects.filter(
                seeker=profile,
                submitted_at__date__gte=start,
            ).count()

        if kind == WeeklyGoal.Kind.SKILLS_ADDED:
            return SeekerSkill.objects.filter(
                seeker=profile,
                created_at__date__gte=start,
            ).count()

        if kind == WeeklyGoal.Kind.COURSES_STARTED:
            return UserLearning.objects.filter(
                user=user,
                started_at__date__gte=start,
            ).count()

        return 0

    @classmethod
    def check_achieved(cls, user, when=None):
        """
        Mark any goal that has been met and award its points.

        Points are awarded once per goal, guarded by achieved_at rather than
        by recounting - a goal met, then exceeded, should not pay twice.
        """
        start = week_start(when)
        awarded = []

        goals = WeeklyGoal.objects.filter(
            user=user,
            week_start=start,
            achieved_at__isnull=True,
        )

        for goal in goals:
            if cls._count(user, goal.kind, start) >= goal.target:
                goal.achieved_at = timezone.now()
                goal.points_awarded = cls.GOAL_POINTS
                goal.save(update_fields=["achieved_at", "points_awarded"])

                PointsService.award(
                    user,
                    cls.GOAL_POINTS,
                    PointsLedger.Reason.GOAL,
                    detail=f"{goal.target} {goal.get_kind_display().lower()}",
                )
                awarded.append(goal.kind)

        return awarded


class PerkService:
    """Spending points on a short trial of a paid feature."""

    @classmethod
    def cost(cls, perk):
        return PERK_COSTS.get(perk)

    @classmethod
    @transaction.atomic
    def redeem(cls, user, perk):
        """
        Buy a 24-hour trial. Refuses if one is already running - paying
        twice for overlapping access would be taking points for nothing.
        """
        cost = cls.cost(perk)
        if cost is None:
            raise ValidationError({"perk": "Unknown perk."})

        if cls.active_perk(user, perk) is not None:
            raise ValidationError(
                {
                    "detail": "You already have this unlocked. " "Redeem again once it expires.",
                }
            )

        PointsService.spend(
            user,
            cost,
            PointsLedger.Reason.REDEMPTION,
            detail=dict(PerkRedemption.Perk.choices)[perk],
        )

        return PerkRedemption.objects.create(
            user=user,
            perk=perk,
            points_spent=cost,
            expires_at=timezone.now() + timedelta(hours=PERK_DURATION_HOURS),
        )

    @classmethod
    def active_perk(cls, user, perk):
        return PerkRedemption.objects.filter(
            user=user,
            perk=perk,
            expires_at__gt=timezone.now(),
        ).first()

    @classmethod
    def has_perk(cls, user, perk):
        """
        Whether a redeemed trial is currently running.

        Checked alongside the plan gate, not instead of it - a Pro user does
        not need a perk, and this must never be the only thing standing
        between a free user and a paid feature.
        """
        return cls.active_perk(user, perk) is not None

    @classmethod
    def available(cls, user):
        balance = PointsService.balance(user)

        return [
            {
                "perk": perk,
                "label": label,
                "cost": PERK_COSTS[perk],
                "affordable": balance >= PERK_COSTS[perk],
                "active_until": (
                    active.expires_at if (active := cls.active_perk(user, perk)) else None
                ),
            }
            for perk, label in PerkRedemption.Perk.choices
        ]
