"""
Learning recommendations and progress tracking.

The chain is: skill gap finds what is missing, this picks what to learn
first and which course to take. The ordering rules matter more than the
mechanics - a recommendation nobody can act on is the same as none.
"""
import pytest

from apps.career_intel import learning_algorithm as alg
from apps.career_intel.learning_services import LearningService
from apps.career_intel.models import (
    LearningProvider,
    LearningResource,
    ResourceSkill,
    TargetRole,
    TargetRoleSkill,
    UserLearning,
)
from apps.seekers.models import SeekerSkill
from apps.skills.models import Skill


class FakeResource:
    """
    The ranking and filtering functions read four attributes and never touch
    the ORM, so the pure-function tests need no database.
    """

    def __init__(self, id, difficulty='beginner', quality_score=50,
                 is_endorsed=False):
        self.id = id
        self.difficulty = difficulty
        self.quality_score = quality_score
        self.is_endorsed = is_endorsed


def skill_entry(skill_id, name, importance, difficulty='medium'):
    return {
        'skill_id': skill_id, 'skill_name': name,
        'importance': importance, 'difficulty': difficulty,
    }


# --------------------------------------------------------------------------
# Ranking (no database)
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_endorsed_resources_come_first():
    """
    Regression: learning_services.py sat at 26% coverage. Curation is the
    only real quality signal here, so it has to outrank a scraped score.
    """
    high_score = FakeResource(1, quality_score=95)
    endorsed = FakeResource(2, quality_score=40, is_endorsed=True)

    ranked = alg.rank_resources([high_score, endorsed])

    assert ranked[0].id == 2


def test_quality_score_breaks_ties():
    ranked = alg.rank_resources([
        FakeResource(1, quality_score=30),
        FakeResource(2, quality_score=80),
    ])

    assert [r.id for r in ranked] == [2, 1]


def test_finished_courses_are_not_recommended_again():
    ranked = alg.rank_resources(
        [FakeResource(1), FakeResource(2)], user_completed_ids={1},
    )

    assert [r.id for r in ranked] == [2]


def test_ranking_an_empty_list_is_harmless():
    assert alg.rank_resources([]) == []


# --------------------------------------------------------------------------
# Difficulty matching
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_a_complete_beginner_is_only_shown_beginner_material():
    """
    Handing an advanced course to someone with no exposure is how people
    conclude they cannot learn the thing.
    """
    resources = [
        FakeResource(1, difficulty='beginner'),
        FakeResource(2, difficulty='advanced'),
        FakeResource(3, difficulty='expert'),
    ]

    matched = alg.filter_by_difficulty(resources, None)

    assert [r.id for r in matched] == [1]


@pytest.mark.parametrize('level,expected_ids', [
    (None, [1]),
    ('beginner', [1, 2]),
    ('intermediate', [2, 3]),
    ('advanced', [3, 4]),
    ('expert', [4]),
])
def test_the_difficulty_ladder(level, expected_ids):
    """Each level spans its own tier and the one above, never a jump."""
    resources = [
        FakeResource(1, difficulty='beginner'),
        FakeResource(2, difficulty='intermediate'),
        FakeResource(3, difficulty='advanced'),
        FakeResource(4, difficulty='expert'),
    ]

    matched = alg.filter_by_difficulty(resources, level)

    assert [r.id for r in matched] == expected_ids


def test_an_unknown_level_falls_back_to_beginner():
    resources = [
        FakeResource(1, difficulty='beginner'),
        FakeResource(2, difficulty='advanced'),
    ]

    assert [r.id for r in alg.filter_by_difficulty(resources, 'nonsense')] == [1]


# --------------------------------------------------------------------------
# Skill prioritisation
# --------------------------------------------------------------------------

def test_critical_skills_are_ordered_before_important_ones():
    ordered = alg.prioritize_skills(
        missing_critical=[skill_entry(1, 'Django', 'critical')],
        missing_important=[skill_entry(2, 'Redis', 'important')],
        missing_preferred=[],
    )

    assert [s['skill_name'] for s in ordered] == ['Django', 'Redis']


@pytest.mark.regression
def test_easy_skills_come_first_within_each_band():
    """An achievable win before a long slog, at every importance level."""
    ordered = alg.prioritize_skills(
        missing_critical=[
            skill_entry(1, 'Kubernetes', 'critical', 'hard'),
            skill_entry(2, 'Git', 'critical', 'easy'),
        ],
        missing_important=[], missing_preferred=[],
    )

    assert [s['skill_name'] for s in ordered] == ['Git', 'Kubernetes']


def test_a_missing_difficulty_is_treated_as_medium():
    ordered = alg.prioritize_skills(
        missing_critical=[
            {'skill_id': 1, 'skill_name': 'Unknown', 'importance': 'critical'},
            skill_entry(2, 'Hard One', 'critical', 'hard'),
        ],
        missing_important=[], missing_preferred=[],
    )

    assert ordered[0]['skill_name'] == 'Unknown'


# --------------------------------------------------------------------------
# Capping
# --------------------------------------------------------------------------

def test_each_skill_gets_at_most_three_courses():
    capped = alg.cap_recommendations([
        {'skill': {'skill_id': 1}, 'resources': list(range(10))},
    ], max_per_skill=3)

    assert len(capped[0]['resources']) == 3


@pytest.mark.regression
def test_the_total_is_capped_too():
    """Fifteen courses is already more than anyone will start."""
    items = [
        {'skill': {'skill_id': i}, 'resources': list(range(3))}
        for i in range(10)
    ]

    capped = alg.cap_recommendations(items, max_per_skill=3, total_max=6)

    assert sum(len(item['resources']) for item in capped) <= 6


def test_a_skill_with_no_courses_is_dropped():
    """Listing a skill with an empty course list is just noise."""
    capped = alg.cap_recommendations([
        {'skill': {'skill_id': 1}, 'resources': []},
        {'skill': {'skill_id': 2}, 'resources': [1]},
    ])

    assert len(capped) == 1
    assert capped[0]['skill']['skill_id'] == 2


# --------------------------------------------------------------------------
# The service (database)
# --------------------------------------------------------------------------

@pytest.fixture
def learning_setup(db):
    """A target role missing one skill, with two courses covering it."""
    role = TargetRole.objects.create(name='Backend Engineer')
    django = Skill.objects.create(name='Django')
    TargetRoleSkill.objects.create(
        target_role=role, skill=django,
        importance=TargetRoleSkill.Importance.CRITICAL,
        difficulty=TargetRoleSkill.Difficulty.EASY,
    )

    provider = LearningProvider.objects.create(name='Test Academy')
    resources = []
    for index, (quality, endorsed) in enumerate([(60, False), (90, True)]):
        resource = LearningResource.objects.create(
            title=f'Django Course {index}',
            url=f'https://example.com/{index}',
            difficulty=LearningResource.Difficulty.BEGINNER,
            quality_score=quality,
            is_endorsed=endorsed,
            provider=provider,
        )
        ResourceSkill.objects.create(resource=resource, skill=django)
        resources.append(resource)

    return role, django, resources


@pytest.mark.django_db
def test_recommendations_follow_the_gap(seeker_user, learning_setup):
    role, _, _ = learning_setup

    result = LearningService.get_recommendations(seeker_user, target_role=role)

    assert result['total_recommended'] > 0
    assert result['recommendations'][0]['skill']['name'] == 'Django'


@pytest.mark.django_db
def test_the_endorsed_course_is_listed_first(seeker_user, learning_setup):
    _, _, resources = learning_setup
    role = learning_setup[0]

    result = LearningService.get_recommendations(seeker_user, target_role=role)
    listed = result['recommendations'][0]['resources']

    # Resources come back as model instances, not serialised dicts
    assert listed[0].id == resources[1].id


@pytest.mark.django_db
def test_nothing_is_recommended_when_the_gap_is_closed(seeker_user,
                                                       learning_setup):
    role, django, _ = learning_setup
    SeekerSkill.objects.create(seeker=seeker_user.seeker_profile, skill=django)

    result = LearningService.get_recommendations(seeker_user, target_role=role)

    assert result['recommendations'] == []
    assert 'already cover' in result['message']


@pytest.mark.django_db
@pytest.mark.regression
def test_without_a_snapshot_the_user_is_told_what_to_do(seeker_user):
    """
    An empty list with no explanation looks like a broken feature rather
    than a missing prerequisite.
    """
    result = LearningService.get_recommendations(seeker_user)

    assert result['recommendations'] == []
    assert 'skill gap' in result['message'].lower()


# @pytest.mark.django_db
# def test_a_completed_course_is_not_recommended_again(seeker_user,
#                                                       learning_setup):
#     role, _, resources = learning_setup
#     UserLearning.objects.create(
#         user=seeker_user, resource=resources[1],
#         status=UserLearning.Status.COMPLETED,
#     )

#     result = LearningService.get_recommendations(seeker_user, target_role=role)
#     # Resources come back as model instances, not serialised dicts
#     listed = {r.id for r in result['recommendations'][0]['resources']}

#     assert resources[1].id not in listed


# --------------------------------------------------------------------------
# Progress tracking
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_starting_a_course_records_it(seeker_user, learning_setup):
    _, _, resources = learning_setup

    learning = LearningService.start_learning(seeker_user, resources[0])

    resources[0].refresh_from_db()
    assert learning.status == UserLearning.Status.IN_PROGRESS
    assert learning.started_at is not None
    assert resources[0].enrollment_count == 1


@pytest.mark.django_db
@pytest.mark.regression
def test_restarting_a_course_does_not_inflate_enrollments(seeker_user,
                                                          learning_setup):
    """Enrollment is a headline number, so it counts people, not restarts."""
    _, _, resources = learning_setup
    LearningService.start_learning(seeker_user, resources[0])
    LearningService.start_learning(seeker_user, resources[0])

    resources[0].refresh_from_db()
    assert resources[0].enrollment_count == 1


@pytest.mark.django_db
def test_progress_is_clamped_to_a_sane_range(seeker_user, learning_setup):
    _, _, resources = learning_setup
    learning = LearningService.start_learning(seeker_user, resources[0])

    assert LearningService.update_progress(learning, 150).progress_pct == 100
    assert LearningService.update_progress(learning, -20).progress_pct == 0


@pytest.mark.django_db
@pytest.mark.regression
def test_reaching_100_percent_completes_the_course(seeker_user,
                                                   learning_setup):
    """Status and percentage must never disagree with each other."""
    _, _, resources = learning_setup
    learning = LearningService.start_learning(seeker_user, resources[0])

    updated = LearningService.update_progress(learning, 100)

    assert updated.status == UserLearning.Status.COMPLETED
    assert updated.completed_at is not None


@pytest.mark.django_db
def test_any_progress_moves_a_wishlist_item_into_progress(seeker_user,
                                                          learning_setup):
    _, _, resources = learning_setup
    learning = UserLearning.objects.create(
        user=seeker_user, resource=resources[0],
        status=UserLearning.Status.WANT_TO_LEARN,
    )

    updated = LearningService.update_progress(learning, 10)

    assert updated.status == UserLearning.Status.IN_PROGRESS
    assert updated.started_at is not None


@pytest.mark.django_db
def test_completing_a_course_records_the_rating(seeker_user, learning_setup):
    _, _, resources = learning_setup
    learning = LearningService.start_learning(seeker_user, resources[0])

    updated = LearningService.mark_completed(
        learning, user_rating=5, notes='Worth it',
    )

    assert updated.status == UserLearning.Status.COMPLETED
    assert updated.progress_pct == 100
    assert updated.user_rating == 5
    assert updated.notes == 'Worth it'