"""
Skill gap analysis.

The algorithm is pure functions and gets exercised directly; the service on
top of it needs the database. Both matter: the gap score is what a Pro
subscriber pays to see, and the recommendation order is the actual product -
telling someone to learn six things is useless, telling them which one to
start with is not.
"""

import pytest

from apps.career_intel import algorithm as alg
from apps.career_intel.models import SkillGapSnapshot, TargetRole, TargetRoleSkill
from apps.career_intel.services import SkillGapService
from apps.seekers.models import SeekerSkill
from apps.skills.models import Skill


class FakeTargetSkill:
    """
    A stand-in for TargetRoleSkill. The algorithm only reads five attributes
    and never touches the ORM, so the pure-function tests need no database.
    """

    def __init__(self, skill_id, name, importance, difficulty="medium"):
        self.skill_id = skill_id
        self.importance = importance
        self.difficulty = difficulty
        self.rationale = ""
        self.skill = type("Skill", (), {"name": name})()


def fake(skill_id, name, importance, difficulty="medium"):
    return FakeTargetSkill(skill_id, name, importance, difficulty)


# --------------------------------------------------------------------------
# Gap score (no database)
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_having_every_skill_is_a_zero_gap():
    """Regression: career_intel/services.py sat at 31% coverage."""
    required = [fake(1, "Python", "critical"), fake(2, "Django", "important")]

    assert alg.compute_gap_score({1, 2}, required) == 0.0


def test_having_none_of_them_is_a_full_gap():
    required = [fake(1, "Python", "critical"), fake(2, "Django", "important")]

    assert alg.compute_gap_score(set(), required) == 100.0


@pytest.mark.regression
def test_a_missing_critical_skill_hurts_more_than_a_missing_optional_one():
    """
    The weighting is the whole idea. Without it, missing a nice-to-have would
    read the same as missing the thing the job is built on.
    """
    required = [fake(1, "Python", "critical"), fake(2, "Figma", "optional")]

    missing_critical = alg.compute_gap_score({2}, required)
    missing_optional = alg.compute_gap_score({1}, required)

    assert missing_critical > missing_optional


def test_a_role_with_no_skills_configured_scores_zero():
    assert alg.compute_gap_score({1, 2}, []) == 0.0


def test_an_unknown_importance_falls_back_to_a_middling_weight():
    """A typo in seed data should not silently weight a skill at zero."""
    required = [fake(1, "Python", "nonsense")]

    assert alg.compute_gap_score(set(), required) == 100.0


@pytest.mark.parametrize(
    "score,category",
    [
        (0, "perfect_fit"),
        (10, "ready"),
        (19.9, "ready"),
        (20, "close"),
        (39.9, "close"),
        (40, "developing"),
        (59.9, "developing"),
        (60, "significant"),
        (100, "significant"),
    ],
)
def test_gap_categories(score, category):
    assert alg.categorize_gap(score) == category


# --------------------------------------------------------------------------
# Splitting
# --------------------------------------------------------------------------


def test_skills_land_in_the_right_buckets():
    required = [
        fake(1, "Python", "critical"),
        fake(2, "Django", "critical"),
        fake(3, "Redis", "important"),
        fake(4, "Figma", "optional"),
    ]

    split = alg.split_skills({1}, required)

    assert [s["skill_name"] for s in split["matched"]] == ["Python"]
    assert [s["skill_name"] for s in split["missing_critical"]] == ["Django"]
    assert [s["skill_name"] for s in split["missing_important"]] == ["Redis"]
    assert [s["skill_name"] for s in split["missing_optional"]] == ["Figma"]


def test_split_entries_carry_what_the_ui_needs():
    split = alg.split_skills(set(), [fake(1, "Python", "critical", "hard")])
    entry = split["missing_critical"][0]

    assert entry["skill_id"] == 1
    assert entry["skill_name"] == "Python"
    assert entry["importance"] == "critical"
    assert entry["difficulty"] == "hard"


# --------------------------------------------------------------------------
# Recommendations
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_the_first_suggestion_is_an_achievable_win():
    """
    Critical-and-easy comes before critical-and-hard on purpose. Opening with
    a three-month project is how people give up.
    """
    split = alg.split_skills(
        set(),
        [
            fake(1, "Kubernetes", "critical", "hard"),
            fake(2, "Git", "critical", "easy"),
        ],
    )

    recommendations = alg.prioritize_recommendations(split)

    assert recommendations[0]["skill_name"] == "Git"


def test_critical_skills_come_before_important_ones():
    split = alg.split_skills(
        set(),
        [
            fake(1, "Redis", "important", "easy"),
            fake(2, "Django", "critical", "medium"),
        ],
    )

    recommendations = alg.prioritize_recommendations(split)

    assert recommendations[0]["skill_name"] == "Django"


@pytest.mark.regression
def test_the_suggestion_list_is_capped():
    """A list of twenty things to learn is the same as no list at all."""
    split = alg.split_skills(set(), [fake(i, f"Skill {i}", "critical", "easy") for i in range(20)])

    assert len(alg.prioritize_recommendations(split, max_count=5)) == 5


def test_optional_skills_are_not_recommended():
    """They are worth showing, but never worth telling someone to go learn."""
    split = alg.split_skills(set(), [fake(1, "Figma", "optional", "easy")])

    assert alg.prioritize_recommendations(split) == []


def test_every_recommendation_explains_itself():
    split = alg.split_skills(set(), [fake(1, "Git", "critical", "easy")])

    reason = alg.prioritize_recommendations(split)[0]["reason"]

    assert "Git" in reason
    assert reason


def test_nothing_missing_means_nothing_to_recommend():
    split = alg.split_skills({1}, [fake(1, "Python", "critical")])

    assert alg.prioritize_recommendations(split) == []


# --------------------------------------------------------------------------
# The service (database)
# --------------------------------------------------------------------------

pytestmark_db = pytest.mark.django_db


@pytest.fixture
def target_role(db):
    role = TargetRole.objects.create(name="Senior Backend Engineer")
    python = Skill.objects.create(name="Python")
    django = Skill.objects.create(name="Django")
    redis = Skill.objects.create(name="Redis")

    TargetRoleSkill.objects.create(
        target_role=role,
        skill=python,
        importance=TargetRoleSkill.Importance.CRITICAL,
        difficulty=TargetRoleSkill.Difficulty.EASY,
    )
    TargetRoleSkill.objects.create(
        target_role=role,
        skill=django,
        importance=TargetRoleSkill.Importance.CRITICAL,
        difficulty=TargetRoleSkill.Difficulty.HARD,
    )
    TargetRoleSkill.objects.create(
        target_role=role,
        skill=redis,
        importance=TargetRoleSkill.Importance.IMPORTANT,
        difficulty=TargetRoleSkill.Difficulty.MEDIUM,
    )
    return role, {"python": python, "django": django, "redis": redis}


@pytest.mark.django_db
def test_a_seeker_with_no_skills_has_the_full_gap(seeker, target_role):
    role, _ = target_role

    result = SkillGapService.analyze(seeker, role)

    assert result["gap_score"] == 100.0
    assert result["category"] == "significant"
    assert result["stats"]["matched"] == 0
    assert result["stats"]["missing_critical"] == 2


@pytest.mark.django_db
def test_matching_skills_close_the_gap(seeker, target_role):
    role, skills = target_role
    SeekerSkill.objects.create(seeker=seeker, skill=skills["python"])
    SeekerSkill.objects.create(seeker=seeker, skill=skills["django"])

    result = SkillGapService.analyze(seeker, role)

    assert result["gap_score"] < 100
    assert result["stats"]["matched"] == 2
    assert result["stats"]["missing_critical"] == 0


@pytest.mark.django_db
def test_having_everything_is_a_perfect_fit(seeker, target_role):
    role, skills = target_role
    for skill in skills.values():
        SeekerSkill.objects.create(seeker=seeker, skill=skill)

    result = SkillGapService.analyze(seeker, role)

    assert result["gap_score"] == 0.0
    assert result["category"] == "perfect_fit"


@pytest.mark.django_db
def test_the_recommendations_start_with_the_easy_critical_skill(seeker, target_role):
    role, _ = target_role

    result = SkillGapService.analyze(seeker, role)

    assert result["recommendations"][0]["skill_name"] == "Python"


@pytest.mark.django_db
@pytest.mark.regression
def test_a_role_with_no_skills_yet_returns_a_full_shape(seeker, db):
    """
    A role added to the taxonomy before its skills are filled in. The
    response has to keep every key the frontend reads, not short-circuit.
    """
    empty_role = TargetRole.objects.create(name="Newly Added Role")

    result = SkillGapService.analyze(seeker, empty_role)

    assert result["gap_score"] == 0.0
    assert result["stats"]["total_required"] == 0
    assert result["missing_skills"] == {
        "critical": [],
        "important": [],
        "preferred": [],
        "optional": [],
    }
    assert result["recommendations"] == []


@pytest.mark.django_db
def test_a_snapshot_records_the_analysis(seeker, target_role):
    role, skills = target_role
    SeekerSkill.objects.create(seeker=seeker, skill=skills["python"])

    snapshot = SkillGapService.save_snapshot(seeker, role, label="before")

    assert isinstance(snapshot, SkillGapSnapshot)
    assert snapshot.matched_count == 1
    assert snapshot.total_required_skills == 3
    assert len(snapshot.missing_skills) == 2


@pytest.mark.django_db
def test_snapshots_let_progress_be_compared_over_time(seeker, target_role):
    """The point of storing them: showing the gap shrinking."""
    role, skills = target_role
    first = SkillGapService.save_snapshot(seeker, role)

    SeekerSkill.objects.create(seeker=seeker, skill=skills["python"])
    SeekerSkill.objects.create(seeker=seeker, skill=skills["django"])
    second = SkillGapService.save_snapshot(seeker, role)

    assert second.gap_score < first.gap_score
    assert SkillGapSnapshot.objects.filter(seeker=seeker).count() == 2
