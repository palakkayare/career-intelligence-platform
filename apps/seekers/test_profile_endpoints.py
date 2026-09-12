"""
The two endpoints that serve a seeker profile.

Regression: `profile_strength_detail` was declared on SeekerProfileSerializer
but missing from Meta.fields. DRF asserts on that as soon as the serializer
builds its fields, so both endpoints raised AssertionError and returned 500 -
in production, for every seeker. Neither endpoint had a test.
"""

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeker_client(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)
    return client


@pytest.mark.regression
def test_a_seeker_can_load_their_own_profile(seeker_client, seeker):
    response = seeker_client.get("/api/v1/seekers/me/")

    assert response.status_code == 200
    assert response.data["id"] == seeker.id


@pytest.mark.regression
def test_the_profile_includes_the_strength_breakdown(seeker_client):
    """The breakdown is what tells a seeker which section to fill in next."""
    detail = seeker_client.get("/api/v1/seekers/me/").data["profile_strength_detail"]

    assert set(detail) == {"score", "breakdown", "next_step"}
    assert 0 <= detail["score"] <= 100
    assert set(detail["breakdown"]) == {
        "basic_info",
        "career_goals",
        "skills",
        "experience",
        "education",
        "portfolio",
    }


def test_the_breakdown_is_read_only(seeker_client):
    """A client must not be able to set its own profile strength."""
    before = seeker_client.get("/api/v1/seekers/me/").data["profile_strength_detail"]["score"]

    response = seeker_client.patch(
        "/api/v1/seekers/me/",
        {"bio": "Backend developer.", "profile_strength_detail": {"score": 100}},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["profile_strength_detail"]["score"] == before


@pytest.mark.regression
def test_another_seeker_can_load_a_public_profile(seeker_user, seeker):
    """The same serializer, so the same crash - reached by a different URL."""
    from apps.accounts.models import User

    viewer = User.objects.create_user(
        email="viewer@test.com",
        password="TestPass123!",
        role=User.Role.SEEKER,
        is_email_verified=True,
    )
    client = APIClient()
    client.force_authenticate(user=viewer)

    response = client.get(f"/api/v1/seekers/{seeker_user.public_id}/")

    assert response.status_code in (200, 403)
    if response.status_code == 200:
        assert "profile_strength_detail" in response.data
