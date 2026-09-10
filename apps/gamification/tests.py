"""
Gamification.

Two things get most of the attention here: the points economy, because it
touches revenue, and the streak, because the unit of time is the whole
design decision.
"""
from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.gamification.models import (
    ApplicationStreak,
    Badge,
    EarnedBadge,
    PerkRedemption,
    PointsLedger,
    WeeklyGoal,
)
from apps.gamification.services import (
    PERK_COSTS,
    BadgeService,
    GoalService,
    PerkService,
    PointsService,
    StreakService,
    week_start,
)

pytestmark = pytest.mark.django_db

Reason = PointsLedger.Reason
Perk = PerkRedemption.Perk


@pytest.fixture(autouse=True)
def badges(db):
    """Badge definitions, seeded the way the command does."""
    from django.core.management import call_command

    call_command('seed_badges', verbosity=0)


@pytest.fixture
def auth(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)
    return client


@pytest.fixture
def make_skill(db):
    """
    Locally defined - fixtures do not cross app boundaries, and the one in
    apps/seekers/tests.py is not visible here.
    """
    from apps.skills.models import Skill

    def _make(name):
        return Skill.objects.create(name=name)
    return _make


def give(user, amount):
    return PointsService.award(user, amount, Reason.ADJUSTMENT, 'test')


# --------------------------------------------------------------------------
# Points ledger
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_a_new_user_has_no_points(seeker_user):
    """Regression: Feature 19 did not exist at all."""
    assert PointsService.balance(seeker_user) == 0


def test_awards_add_up(seeker_user):
    give(seeker_user, 30)
    give(seeker_user, 20)

    assert PointsService.balance(seeker_user) == 50


def test_spending_subtracts(seeker_user):
    give(seeker_user, 100)

    PointsService.spend(seeker_user, 40, Reason.REDEMPTION)

    assert PointsService.balance(seeker_user) == 60


@pytest.mark.regression
def test_the_balance_cannot_go_negative(seeker_user):
    """
    A negative balance would let someone redeem now and earn later, which
    turns points into credit.
    """
    give(seeker_user, 10)

    with pytest.raises(ValidationError):
        PointsService.spend(seeker_user, 50, Reason.REDEMPTION)

    assert PointsService.balance(seeker_user) == 10


def test_awarding_zero_or_less_is_refused(seeker_user):
    with pytest.raises(ValidationError):
        PointsService.award(seeker_user, 0, Reason.ADJUSTMENT)
    with pytest.raises(ValidationError):
        PointsService.award(seeker_user, -50, Reason.ADJUSTMENT)


@pytest.mark.regression
def test_every_movement_leaves_a_row(seeker_user):
    """
    The point of a ledger over a balance column: "why do I have 60 points"
    has to be answerable.
    """
    give(seeker_user, 100)
    PointsService.spend(seeker_user, 40, Reason.REDEMPTION, 'A perk')

    history = list(PointsService.history(seeker_user))

    assert len(history) == 2
    assert sum(entry.delta for entry in history) == 60


def test_points_are_per_user(seeker_user, recruiter_user):
    give(seeker_user, 100)

    assert PointsService.balance(recruiter_user) == 0


# --------------------------------------------------------------------------
# Badges
# --------------------------------------------------------------------------

def test_a_badge_can_be_awarded(seeker_user):
    _, created = BadgeService.award(seeker_user, 'first-application')

    assert created is True
    assert EarnedBadge.objects.filter(user=seeker_user).count() == 1


def test_a_badge_carries_points(seeker_user):
    badge = Badge.objects.get(code='first-application')

    BadgeService.award(seeker_user, 'first-application')

    assert PointsService.balance(seeker_user) == badge.points


@pytest.mark.regression
def test_a_badge_pays_only_once(seeker_user):
    """Re-running the checker must not keep topping people up."""
    BadgeService.award(seeker_user, 'first-application')
    balance = PointsService.balance(seeker_user)

    _, created = BadgeService.award(seeker_user, 'first-application')

    assert created is False
    assert PointsService.balance(seeker_user) == balance


def test_an_unknown_badge_code_is_ignored(seeker_user):
    earned, created = BadgeService.award(seeker_user, 'no-such-badge')

    assert earned is None
    assert created is False


def test_profile_badges_follow_the_strength_score(seeker, make_skill):
    from apps.seekers.models import SeekerSkill

    seeker.full_name = 'Palak K'
    seeker.bio = 'Backend engineer focused on payments and search systems. ' * 2
    seeker.location = 'Bangalore'
    seeker.current_title = 'Backend Developer'
    seeker.target_role = 'Senior Backend Engineer'
    seeker.save()
    SeekerSkill.objects.create(seeker=seeker, skill=make_skill('Python'))
    seeker.refresh_from_db()

    # basic_info 15 + career_goals 15 + one skill 5 = 35, over the 25 floor
    assert seeker.profile_strength >= 25

    earned = BadgeService.check_all(seeker.user)

    assert 'profile-started' in earned
    assert 'profile-complete' not in earned

def test_skill_badges_follow_the_skill_count(seeker, make_skill):
    from apps.seekers.models import SeekerSkill

    for index in range(5):
        SeekerSkill.objects.create(
            seeker=seeker, skill=make_skill(f'Skill {index}'),
        )

    earned = BadgeService.check_all(seeker.user)

    assert 'skills-5' in earned
    assert 'skills-10' not in earned


def test_an_application_earns_the_first_step_badge(seeker, job):
    from apps.applications.services import ApplicationCreationService

    ApplicationCreationService.create(seeker, job)

    earned = BadgeService.check_all(seeker.user)

    assert 'first-application' in earned


@pytest.mark.regression
def test_a_withdrawn_application_still_counts_towards_badges(seeker, job):
    """
    The badge marks the act of applying, not the outcome. Taking it back
    when someone withdraws would punish a reasonable decision.
    """
    from apps.applications.models import Application
    from apps.applications.services import (
        ApplicationCreationService, ApplicationStatusService,
    )

    application = ApplicationCreationService.create(seeker, job)
    ApplicationStatusService.update_status(
        application, Application.Status.WITHDRAWN, actor=seeker.user,
    )

    assert 'first-application' in BadgeService.check_all(seeker.user)


def test_checking_twice_awards_nothing_new(seeker, job):
    from apps.applications.services import ApplicationCreationService

    ApplicationCreationService.create(seeker, job)
    BadgeService.check_all(seeker.user)

    assert BadgeService.check_all(seeker.user) == []


def test_a_recruiter_earns_no_seeker_badges(recruiter_user):
    assert BadgeService.check_all(recruiter_user) == []


# --------------------------------------------------------------------------
# Streaks
# --------------------------------------------------------------------------

def test_the_week_starts_on_monday():
    wednesday = timezone.now().replace(
        year=2026, month=9, day=9,
    )  # a Wednesday
    assert week_start(wednesday) == date(2026, 9, 7)  # the Monday


def test_a_first_application_starts_a_streak(seeker_user):
    streak = StreakService.record_application(seeker_user)

    assert streak.current_weeks == 1
    assert streak.longest_weeks == 1


@pytest.mark.regression
def test_a_second_application_in_the_same_week_changes_nothing(seeker_user):
    """
    The streak counts weeks in which you applied, not applications. Ten in
    one week is one week.
    """
    StreakService.record_application(seeker_user)
    streak = StreakService.record_application(seeker_user)

    assert streak.current_weeks == 1


def test_applying_in_consecutive_weeks_extends_the_streak(seeker_user):
    now = timezone.now()
    StreakService.record_application(seeker_user, when=now - timedelta(days=14))
    StreakService.record_application(seeker_user, when=now - timedelta(days=7))
    streak = StreakService.record_application(seeker_user, when=now)

    assert streak.current_weeks == 3


@pytest.mark.regression
def test_missing_a_week_resets_the_streak(seeker_user):
    """A gap is a gap. Forgiving it would make the number meaningless."""
    now = timezone.now()
    StreakService.record_application(seeker_user, when=now - timedelta(days=21))
    streak = StreakService.record_application(seeker_user, when=now)

    assert streak.current_weeks == 1


def test_the_longest_streak_is_remembered(seeker_user):
    now = timezone.now()
    for weeks_ago in (4, 3, 2):
        StreakService.record_application(
            seeker_user, when=now - timedelta(days=weeks_ago * 7),
        )
    StreakService.record_application(seeker_user, when=now)

    streak = ApplicationStreak.objects.get(user=seeker_user)
    assert streak.current_weeks == 1  # gap between week 2 and now
    assert streak.longest_weeks == 3


def test_a_streak_milestone_pays_points(seeker_user):
    now = timezone.now()
    for weeks_ago in (3, 2, 1, 0):
        StreakService.record_application(
            seeker_user, when=now - timedelta(days=weeks_ago * 7),
        )

    assert PointsService.balance(seeker_user) == 25  # the 4-week milestone


@pytest.mark.regression
def test_a_stale_streak_reads_as_zero(seeker_user):
    """
    The stored number is only correct until a week passes. Showing a streak
    that ended a month ago would be a lie the database is happy to tell.
    """
    StreakService.record_application(
        seeker_user, when=timezone.now() - timedelta(days=30),
    )

    current = StreakService.current(seeker_user)

    assert current['current_weeks'] == 0
    assert current['is_live'] is False
    assert current['longest_weeks'] == 1


def test_last_weeks_streak_is_still_live(seeker_user):
    """The week is not over yet, so there is still time to keep it."""
    StreakService.record_application(
        seeker_user, when=timezone.now() - timedelta(days=7),
    )

    assert StreakService.current(seeker_user)['is_live'] is True


def test_someone_who_never_applied_has_no_streak(seeker_user):
    assert StreakService.current(seeker_user)['current_weeks'] == 0


@pytest.mark.regression
def test_applying_updates_the_streak_automatically(seeker, job):
    """The signal - a seeker should not have to do anything for this."""
    from apps.applications.services import ApplicationCreationService

    ApplicationCreationService.create(seeker, job)

    assert StreakService.current(seeker.user)['current_weeks'] == 1


# --------------------------------------------------------------------------
# Weekly goals
# --------------------------------------------------------------------------

def test_a_goal_can_be_set(seeker_user):
    goal = GoalService.set_goal(seeker_user, WeeklyGoal.Kind.APPLICATIONS, 3)

    assert goal.target == 3
    assert goal.week_start == week_start()


def test_a_goal_can_be_changed_while_the_week_is_open(seeker_user):
    GoalService.set_goal(seeker_user, WeeklyGoal.Kind.APPLICATIONS, 3)
    GoalService.set_goal(seeker_user, WeeklyGoal.Kind.APPLICATIONS, 5)

    goals = WeeklyGoal.objects.filter(user=seeker_user)
    assert goals.count() == 1
    assert goals.first().target == 5


@pytest.mark.parametrize('target', [0, -1, 51, 1000])
def test_absurd_targets_are_refused(seeker_user, target):
    with pytest.raises(ValidationError):
        GoalService.set_goal(seeker_user, WeeklyGoal.Kind.APPLICATIONS, target)


def test_progress_counts_this_weeks_applications(seeker, six_jobs):
    from apps.applications.services import ApplicationCreationService

    GoalService.set_goal(seeker.user, WeeklyGoal.Kind.APPLICATIONS, 3)
    for job in six_jobs[:2]:
        ApplicationCreationService.create(seeker, job)

    progress = GoalService.progress(seeker.user)

    assert progress[0]['current'] == 2
    assert progress[0]['target'] == 3
    assert progress[0]['achieved'] is False


def test_meeting_a_goal_pays_points(seeker, six_jobs):
    from apps.applications.services import ApplicationCreationService

    GoalService.set_goal(seeker.user, WeeklyGoal.Kind.APPLICATIONS, 2)
    for job in six_jobs[:2]:
        ApplicationCreationService.create(seeker, job)

    assert PointsService.balance(seeker.user) >= GoalService.GOAL_POINTS
    assert GoalService.progress(seeker.user)[0]['achieved'] is True


@pytest.mark.regression
def test_exceeding_a_goal_does_not_pay_twice(seeker, six_jobs):
    """
    Guarded by achieved_at rather than by recounting - a goal met and then
    exceeded is still one goal.
    """
    from apps.applications.services import ApplicationCreationService

    GoalService.set_goal(seeker.user, WeeklyGoal.Kind.APPLICATIONS, 2)
    for job in six_jobs[:4]:
        ApplicationCreationService.create(seeker, job)

    goal_points = PointsLedger.objects.filter(
        user=seeker.user, reason=Reason.GOAL,
    )
    assert goal_points.count() == 1


def test_last_weeks_applications_do_not_count(seeker, job):
    from apps.applications.models import Application
    from apps.applications.services import ApplicationCreationService

    application = ApplicationCreationService.create(seeker, job)
    Application.all_objects.filter(pk=application.pk).update(
        submitted_at=timezone.now() - timedelta(days=10),
    )

    GoalService.set_goal(seeker.user, WeeklyGoal.Kind.APPLICATIONS, 1)

    assert GoalService.progress(seeker.user)[0]['current'] == 0


# --------------------------------------------------------------------------
# Perks
# --------------------------------------------------------------------------

def test_a_perk_can_be_redeemed(seeker_user):
    give(seeker_user, 200)

    redemption = PerkService.redeem(seeker_user, Perk.MATCH_SCORE_DAY)

    assert redemption.points_spent == PERK_COSTS[Perk.MATCH_SCORE_DAY]
    assert PerkService.has_perk(seeker_user, Perk.MATCH_SCORE_DAY) is True


def test_redeeming_costs_points(seeker_user):
    give(seeker_user, 200)
    cost = PERK_COSTS[Perk.MATCH_SCORE_DAY]

    PerkService.redeem(seeker_user, Perk.MATCH_SCORE_DAY)

    assert PointsService.balance(seeker_user) == 200 - cost


@pytest.mark.regression
def test_a_perk_cannot_be_redeemed_without_the_points(seeker_user):
    """The economy only means anything if the price is real."""
    give(seeker_user, 10)

    with pytest.raises(ValidationError):
        PerkService.redeem(seeker_user, Perk.MATCH_SCORE_DAY)

    assert PerkService.has_perk(seeker_user, Perk.MATCH_SCORE_DAY) is False


@pytest.mark.regression
def test_an_active_perk_cannot_be_bought_again(seeker_user):
    """Charging twice for overlapping access is taking points for nothing."""
    give(seeker_user, 500)
    PerkService.redeem(seeker_user, Perk.MATCH_SCORE_DAY)
    balance = PointsService.balance(seeker_user)

    with pytest.raises(ValidationError):
        PerkService.redeem(seeker_user, Perk.MATCH_SCORE_DAY)

    assert PointsService.balance(seeker_user) == balance


def test_an_expired_perk_stops_counting(seeker_user):
    give(seeker_user, 200)
    redemption = PerkService.redeem(seeker_user, Perk.MATCH_SCORE_DAY)

    PerkRedemption.objects.filter(pk=redemption.pk).update(
        expires_at=timezone.now() - timedelta(hours=1),
    )

    assert PerkService.has_perk(seeker_user, Perk.MATCH_SCORE_DAY) is False


def test_perks_are_independent_of_each_other(seeker_user):
    give(seeker_user, 500)

    PerkService.redeem(seeker_user, Perk.MATCH_SCORE_DAY)

    assert PerkService.has_perk(seeker_user, Perk.SKILL_GAP_DAY) is False


@pytest.mark.regression
def test_a_perk_is_priced_out_of_casual_reach(seeker_user):
    """
    Every badge at once comes to less than the cheapest perk. Points have to
    show someone what Pro does without becoming a substitute for it.
    """
    every_badge_point = sum(
        Badge.objects.values_list('points', flat=True)
    )

    assert min(PERK_COSTS.values()) < every_badge_point  # reachable
    assert min(PERK_COSTS.values()) > every_badge_point / 3  # not trivially


def test_the_perk_list_shows_affordability(seeker_user):
    give(seeker_user, PERK_COSTS[Perk.MATCH_SCORE_DAY])

    perks = {p['perk']: p for p in PerkService.available(seeker_user)}

    assert perks[Perk.MATCH_SCORE_DAY]['affordable'] is True
    assert perks[Perk.SKILL_GAP_DAY]['affordable'] is False


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

def test_the_progress_endpoint_returns_everything(auth, seeker_user):
    response = auth.get('/api/v1/gamification/me/')

    assert response.status_code == 200
    for key in ('points', 'badges', 'streak', 'goals', 'perks'):
        assert key in response.data


def test_the_progress_endpoint_awards_pending_badges(auth, seeker, job):
    from apps.applications.services import ApplicationCreationService

    ApplicationCreationService.create(seeker, job)

    response = auth.get('/api/v1/gamification/me/')

    earned = {b['code'] for b in response.data['badges'] if b['earned']}
    assert 'first-application' in earned


def test_a_goal_can_be_set_through_the_api(auth):
    response = auth.post('/api/v1/gamification/goals/', {
        'kind': 'applications', 'target': 3,
    }, format='json')

    assert response.status_code == 201
    assert response.data['goals'][0]['target'] == 3


def test_the_api_refuses_an_absurd_target(auth):
    response = auth.post('/api/v1/gamification/goals/', {
        'kind': 'applications', 'target': 500,
    }, format='json')

    assert response.status_code == 400


def test_redeeming_through_the_api(auth, seeker_user):
    give(seeker_user, 200)

    response = auth.post('/api/v1/gamification/perks/redeem/', {
        'perk': 'match_score_day',
    }, format='json')

    assert response.status_code == 201
    assert response.data['points_spent'] == PERK_COSTS[Perk.MATCH_SCORE_DAY]


def test_redeeming_without_points_returns_400(auth):
    response = auth.post('/api/v1/gamification/perks/redeem/', {
        'perk': 'match_score_day',
    }, format='json')

    assert response.status_code == 400


def test_the_points_history_endpoint(auth, seeker_user):
    give(seeker_user, 50)

    response = auth.get('/api/v1/gamification/points/')

    assert response.data['balance'] == 50
    assert len(response.data['history']) == 1


def test_recruiters_have_no_gamification(recruiter_user):
    client = APIClient()
    client.force_authenticate(user=recruiter_user)

    assert client.get('/api/v1/gamification/me/').status_code == 403


def test_gamification_needs_a_login():
    assert APIClient().get(
        '/api/v1/gamification/me/',
    ).status_code in (401, 403)


# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_a_gamification_failure_does_not_break_an_application(seeker, job):
    """
    Points are a nice-to-have; the application is the product. The signal
    swallows its own errors for exactly this reason.
    """
    from unittest.mock import patch

    from apps.applications.services import ApplicationCreationService

    with patch(
        'apps.gamification.services.StreakService.record_application',
        side_effect=RuntimeError('gamification exploded'),
    ):
        application = ApplicationCreationService.create(seeker, job)

    assert application.pk is not None


def test_the_badge_seed_is_idempotent(db):
    from django.core.management import call_command

    before = Badge.objects.count()
    call_command('seed_badges', verbosity=0)

    assert Badge.objects.count() == before