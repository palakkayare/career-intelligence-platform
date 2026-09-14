"""
The list of interviews a person has started a checklist for.

Regression: Meta.ordering put completed_at into the SELECT, so DISTINCT ran
over (label, completed_at) and returned one row per tick. Six ticked items for
one interview came back as six copies of that interview.
"""

import pytest

from apps.interview_prep.models import InterviewChecklistItem
from apps.interview_prep.services import InterviewPrepService

pytestmark = pytest.mark.django_db


@pytest.fixture
def items(db):
    return [
        InterviewChecklistItem.objects.create(
            phase=InterviewChecklistItem.Phase.PREPARATION,
            text=f"Item {index}",
            detail="",
            order=index,
            is_active=True,
        )
        for index in range(3)
    ]


@pytest.mark.regression
def test_one_interview_is_listed_once_however_many_items_are_ticked(seeker_user, items):
    for item in items:
        InterviewPrepService.tick(seeker_user, item, "Acme - round 2")

    assert InterviewPrepService.my_interviews(seeker_user) == ["Acme - round 2"]


def test_each_interview_is_listed_once(seeker_user, items):
    for item in items:
        InterviewPrepService.tick(seeker_user, item, "Acme")
        InterviewPrepService.tick(seeker_user, item, "Globex")

    assert InterviewPrepService.my_interviews(seeker_user) == ["Acme", "Globex"]


def test_the_order_is_stable(seeker_user, items):
    """
    Alphabetical, not "whichever was ticked last" - a list that reshuffles
    itself as you tick things is hard to click.
    """
    for label in ("Zebra", "Acme", "Mango"):
        InterviewPrepService.tick(seeker_user, items[0], label)

    assert InterviewPrepService.my_interviews(seeker_user) == ["Acme", "Mango", "Zebra"]


def test_another_persons_interviews_are_not_listed(seeker_user, items):
    from apps.accounts.models import User

    other = User.objects.create_user(email="other@test.com", password="TestPass123!")
    InterviewPrepService.tick(other, items[0], "Not yours")

    assert InterviewPrepService.my_interviews(seeker_user) == []


def test_someone_who_has_ticked_nothing_gets_an_empty_list(seeker_user):
    assert InterviewPrepService.my_interviews(seeker_user) == []
