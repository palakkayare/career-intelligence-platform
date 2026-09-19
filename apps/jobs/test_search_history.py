"""
One piece of searching should leave one row.

Before this, every request wrote its own row: typing a query, adding a city,
then trying On-site, Hybrid and Remote in turn filled the whole ten-row
history with a single afternoon's work.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.jobs.models import SearchHistory
from apps.jobs.search_history import CONTINUATION_WINDOW, record_search

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeker(django_user_model):
    return django_user_model.objects.create_user(
        email="searcher@test.com", password="pw-12345678", role="seeker", is_email_verified=True
    )


def rows(user):
    return list(SearchHistory.objects.filter(user=user).order_by("-created_at"))


def test_typing_a_query_leaves_one_row(seeker):
    for text in ("back", "backend", "backend developer"):
        record_search(seeker, text, {}, 3)

    assert [r.query_text for r in rows(seeker)] == ["backend developer"]


def test_trying_filters_on_the_same_search_leaves_one_row(seeker):
    record_search(seeker, "backend developer", {}, 12)
    record_search(seeker, "backend developer", {"work_arrangement": "onsite"}, 4)
    record_search(seeker, "backend developer", {"work_arrangement": "hybrid"}, 6)
    record_search(seeker, "backend developer", {"work_arrangement": "remote"}, 2)

    remaining = rows(seeker)
    assert len(remaining) == 1
    # The row keeps where the search ended up, not where it started.
    assert remaining[0].filters == {"work_arrangement": "remote"}
    assert remaining[0].result_count == 2


def test_deleting_words_to_widen_is_still_the_same_search(seeker):
    record_search(seeker, "backend developer", {}, 3)
    record_search(seeker, "backend", {}, 30)

    assert [r.query_text for r in rows(seeker)] == ["backend"]


def test_a_different_search_gets_its_own_row(seeker):
    record_search(seeker, "backend developer", {}, 12)
    record_search(seeker, "data analyst", {}, 7)

    assert [r.query_text for r in rows(seeker)] == ["data analyst", "backend developer"]


def test_the_same_words_tomorrow_are_a_new_row(seeker):
    first = record_search(seeker, "backend developer", {}, 12)
    SearchHistory.objects.filter(pk=first.pk).update(
        created_at=timezone.now() - CONTINUATION_WINDOW - timedelta(minutes=1)
    )

    record_search(seeker, "backend developer", {}, 12)

    assert len(rows(seeker)) == 2


def test_an_empty_search_is_not_recorded(seeker):
    assert record_search(seeker, "", {}, 0) is None
    assert rows(seeker) == []


def test_history_stays_within_its_limit(seeker):
    for n in range(SearchHistory.MAX_PER_USER + 5):
        record_search(seeker, f"role number {n}", {}, n)

    assert len(rows(seeker)) == SearchHistory.MAX_PER_USER


def test_one_person_does_not_collapse_into_another(django_user_model, seeker):
    other = django_user_model.objects.create_user(
        email="other@test.com", password="pw-12345678", role="seeker", is_email_verified=True
    )
    record_search(seeker, "backend developer", {}, 3)
    record_search(other, "backend developer", {}, 3)

    assert len(rows(seeker)) == 1
    assert len(rows(other)) == 1
