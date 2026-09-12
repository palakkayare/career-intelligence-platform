"""
GET /api/v1/career-path/from-current/ resolves the seeker's own title.
"""

import pytest
from rest_framework.test import APIClient

from apps.career_intel.models import CareerPathNode

pytestmark = pytest.mark.django_db


@pytest.fixture
def graph(db):
    for name, slug, level in [
        ("Junior Backend Developer", "junior-backend-developer", 2),
        ("Backend Developer", "backend-developer", 3),
        ("Senior Backend Developer", "senior-backend-developer", 4),
        ("Data Scientist", "data-scientist", 3),
    ]:
        CareerPathNode.objects.create(name=name, slug=slug, level=level, is_active=True)


@pytest.fixture
def client(seeker_user, plans):
    """The endpoint is a paid feature, so the trial plan has to carry it."""
    plans["pro"].has_career_path = True
    plans["pro"].save(update_fields=["has_career_path"])
    api = APIClient()
    api.force_authenticate(user=seeker_user)
    return api


def ask(client, seeker, title):
    seeker.current_title = title
    seeker.save(update_fields=["current_title"])
    return client.get("/api/v1/career-path/from-current/")


@pytest.mark.regression
def test_a_loosely_written_title_resolves_to_the_right_level(client, seeker, graph):
    """The bug: this resolved to Junior Backend Developer."""
    response = ask(client, seeker, "Backend Engineer")

    assert response.status_code == 200
    assert response.data["matched_node"]["name"] == "Backend Developer"


def test_the_response_says_which_node_it_matched(client, seeker, graph):
    response = ask(client, seeker, "Sr. Backend Developer")

    assert response.data["matched_node"]["name"] == "Senior Backend Developer"
    assert response.data["matched_from_title"] == "Sr. Backend Developer"
    assert response.data["matched_exactly"] is False


def test_an_exact_title_is_reported_as_exact(client, seeker, graph):
    response = ask(client, seeker, "Backend Developer")

    assert response.data["matched_exactly"] is True


def test_an_unmatchable_title_returns_suggestions(client, seeker, graph):
    response = ask(client, seeker, "Chef")

    assert response.status_code == 404
    assert response.data["suggestions"]
    assert all({"slug", "name"} == set(item) for item in response.data["suggestions"])


def test_a_missing_title_asks_for_one(client, seeker, graph):
    response = ask(client, seeker, "")

    assert response.status_code == 400
