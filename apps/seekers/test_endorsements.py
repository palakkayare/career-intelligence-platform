"""
Skill endorsements.

An endorsement is only worth something if it is hard to manufacture, so most
of these tests are about the two cheap ways to fake one: endorsing yourself,
and clicking twice.
"""

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.seekers.models import SeekerSkill, SkillEndorsement
from apps.seekers.services import SkillEndorsementService
from apps.skills.models import Skill

pytestmark = pytest.mark.django_db


@pytest.fixture
def python_skill(db):
    return Skill.objects.create(name="Python")


@pytest.fixture
def seeker_skill(seeker, python_skill):
    return SeekerSkill.objects.create(seeker=seeker, skill=python_skill)


def make_endorser(email="endorser@test.com"):
    return User.objects.create_user(
        email=email,
        password="TestPass123!",
        role=User.Role.SEEKER,
        is_email_verified=True,
    )


@pytest.fixture
def endorser(plans):
    return make_endorser()


# --------------------------------------------------------------------------
# Endorsing
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_someone_can_endorse_a_skill(seeker_skill, endorser):
    """Regression: Feature 12 lists skill endorsements; none existed."""
    endorsement, created = SkillEndorsementService.endorse(
        seeker_skill,
        endorser,
    )

    seeker_skill.refresh_from_db()
    assert created is True
    assert endorsement.endorsed_by == endorser
    assert seeker_skill.endorsement_count == 1


@pytest.mark.regression
def test_nobody_can_endorse_their_own_skill(seeker_skill, seeker):
    """The cheapest possible way to manufacture credibility."""
    with pytest.raises(ValidationError):
        SkillEndorsementService.endorse(seeker_skill, seeker.user)

    seeker_skill.refresh_from_db()
    assert seeker_skill.endorsement_count == 0


@pytest.mark.regression
def test_one_person_counts_once_however_many_times_they_click(seeker_skill, endorser):
    """
    An enthusiastic supporter clicking five times must not look like five
    people.
    """
    for _ in range(5):
        SkillEndorsementService.endorse(seeker_skill, endorser)

    seeker_skill.refresh_from_db()
    assert seeker_skill.endorsement_count == 1
    assert SkillEndorsement.objects.filter(seeker_skill=seeker_skill).count() == 1


def test_a_repeat_endorsement_is_not_an_error(seeker_skill, endorser):
    """Clicking an already-endorsed button should be a no-op, not a 400."""
    SkillEndorsementService.endorse(seeker_skill, endorser)

    _, created = SkillEndorsementService.endorse(seeker_skill, endorser)

    assert created is False


def test_different_people_each_count(seeker_skill, plans):
    for index in range(3):
        SkillEndorsementService.endorse(
            seeker_skill,
            make_endorser(f"e{index}@test.com"),
        )

    seeker_skill.refresh_from_db()
    assert seeker_skill.endorsement_count == 3


def test_endorsements_are_per_skill_not_per_person(seeker, endorser, python_skill):
    django = Skill.objects.create(name="Django")
    python_row = SeekerSkill.objects.create(seeker=seeker, skill=python_skill)
    django_row = SeekerSkill.objects.create(seeker=seeker, skill=django)

    SkillEndorsementService.endorse(python_row, endorser)

    python_row.refresh_from_db()
    django_row.refresh_from_db()
    assert python_row.endorsement_count == 1
    assert django_row.endorsement_count == 0


# --------------------------------------------------------------------------
# Withdrawing
# --------------------------------------------------------------------------


def test_an_endorsement_can_be_taken_back(seeker_skill, endorser):
    SkillEndorsementService.endorse(seeker_skill, endorser)

    removed = SkillEndorsementService.withdraw(seeker_skill, endorser)

    seeker_skill.refresh_from_db()
    assert removed is True
    assert seeker_skill.endorsement_count == 0


def test_withdrawing_what_was_never_given_reports_so(seeker_skill, endorser):
    assert SkillEndorsementService.withdraw(seeker_skill, endorser) is False


def test_withdrawing_leaves_other_endorsements_alone(seeker_skill, plans):
    first = make_endorser("first@test.com")
    second = make_endorser("second@test.com")
    SkillEndorsementService.endorse(seeker_skill, first)
    SkillEndorsementService.endorse(seeker_skill, second)

    SkillEndorsementService.withdraw(seeker_skill, first)

    seeker_skill.refresh_from_db()
    assert seeker_skill.endorsement_count == 1


@pytest.mark.regression
def test_deleting_the_skill_takes_its_endorsements_with_it(seeker_skill, endorser):
    """An endorsement of a skill nobody claims any more means nothing."""
    SkillEndorsementService.endorse(seeker_skill, endorser)
    skill_id = seeker_skill.pk

    seeker_skill.delete()

    assert not SkillEndorsement.objects.filter(seeker_skill_id=skill_id).exists()


def test_a_withdrawn_endorsement_stops_counting(seeker_skill, plans):
    """
    Users are never hard-deleted here - Subscription.user is PROTECT, and
    account closure is a soft delete. Removing the endorsement row is the
    path that actually happens.
    """
    first = make_endorser("first-leaver@test.com")
    second = make_endorser("second-stays@test.com")
    SkillEndorsementService.endorse(seeker_skill, first)
    SkillEndorsementService.endorse(seeker_skill, second)

    SkillEndorsement.objects.filter(endorsed_by=first).delete()

    seeker_skill.refresh_from_db()
    assert seeker_skill.endorsement_count == 1


# --------------------------------------------------------------------------
# The counter
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_the_counter_is_rebuildable_from_the_rows(seeker_skill, endorser):
    """
    The count is denormalised, so it can drift. Recomputing has to be able
    to put it right.
    """
    SkillEndorsementService.endorse(seeker_skill, endorser)
    SeekerSkill.objects.filter(pk=seeker_skill.pk).update(endorsement_count=99)
    seeker_skill.refresh_from_db()

    SkillEndorsementService.refresh_count(seeker_skill)

    seeker_skill.refresh_from_db()
    assert seeker_skill.endorsement_count == 1


def test_endorsing_does_not_change_the_profile_strength(seeker, seeker_skill, endorser):
    """
    Endorsements are other people's opinions. Letting them move a score the
    owner is told to improve would be a strange incentive.
    """
    seeker.refresh_from_db()
    before = seeker.profile_strength

    SkillEndorsementService.endorse(seeker_skill, endorser)

    seeker.refresh_from_db()
    assert seeker.profile_strength == before


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


def endorse_url(seeker_skill):
    return f"/api/v1/seekers/skills/{seeker_skill.pk}/endorse/"


def test_the_endpoint_records_an_endorsement(seeker_skill, endorser):
    client = APIClient()
    client.force_authenticate(user=endorser)

    response = client.post(endorse_url(seeker_skill))

    assert response.status_code == 201
    assert response.data["endorsement_count"] == 1
    assert response.data["endorsed"] is True


def test_the_endpoint_is_idempotent(seeker_skill, endorser):
    client = APIClient()
    client.force_authenticate(user=endorser)
    client.post(endorse_url(seeker_skill))

    response = client.post(endorse_url(seeker_skill))

    assert response.status_code == 200
    assert response.data["endorsement_count"] == 1


def test_the_endpoint_refuses_self_endorsement(seeker_skill, seeker):
    client = APIClient()
    client.force_authenticate(user=seeker.user)

    assert client.post(endorse_url(seeker_skill)).status_code == 400


def test_the_endpoint_can_withdraw(seeker_skill, endorser):
    client = APIClient()
    client.force_authenticate(user=endorser)
    client.post(endorse_url(seeker_skill))

    response = client.delete(endorse_url(seeker_skill))

    assert response.status_code == 200
    assert response.data["endorsement_count"] == 0
    assert response.data["endorsed"] is False


def test_withdrawing_without_endorsing_returns_404(seeker_skill, endorser):
    client = APIClient()
    client.force_authenticate(user=endorser)

    assert client.delete(endorse_url(seeker_skill)).status_code == 404


def test_endorsing_requires_a_login(seeker_skill):
    assert APIClient().post(endorse_url(seeker_skill)).status_code in (401, 403)


def test_endorsing_an_unknown_skill_returns_404(endorser):
    client = APIClient()
    client.force_authenticate(user=endorser)

    assert client.post("/api/v1/seekers/skills/999999/endorse/").status_code == 404
