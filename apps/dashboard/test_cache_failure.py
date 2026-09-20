"""
A cache that is down must not take writes or screens down with it.

Redis is a dependency for speed, not for correctness. Saving a profile fires
a signal that clears the cached dashboard; if that clearing can raise, then a
Redis blip turns every profile save into a 500. The same goes for the
dashboard endpoint itself.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.dashboard.services import invalidate

pytestmark = pytest.mark.django_db


class BrokenCache:
    """Stands in for a Redis that cannot be reached."""

    def __getattr__(self, _name):
        def raiser(*args, **kwargs):
            raise ConnectionError("Redis is unreachable")

        return raiser


@pytest.fixture
def seeker(django_user_model):
    return django_user_model.objects.create_user(
        email="cache-test@seeker.test",
        password="pw-12345678",
        role="seeker",
        is_email_verified=True,
    )


def test_a_profile_save_survives_a_dead_cache(monkeypatch, seeker):
    monkeypatch.setattr("apps.dashboard.services.cache", BrokenCache())

    profile = seeker.seeker_profile
    profile.location = "Pune"
    profile.save()  # the signal calls invalidate(); it must not raise

    profile.refresh_from_db()
    assert profile.location == "Pune"


def test_invalidate_does_not_raise_on_its_own(monkeypatch, seeker):
    monkeypatch.setattr("apps.dashboard.services.cache", BrokenCache())
    invalidate(seeker.pk)  # no exception


def test_the_dashboard_still_loads_without_a_cache(monkeypatch, seeker):
    monkeypatch.setattr("apps.dashboard.views.cache", BrokenCache())
    client = APIClient()
    client.force_authenticate(seeker)

    response = client.get("/api/v1/dashboard/me/")

    assert response.status_code == 200
    assert "errors" in response.json()


def test_the_cache_is_still_used_when_it_works(seeker):
    cache.clear()
    client = APIClient()
    client.force_authenticate(seeker)

    client.get("/api/v1/dashboard/me/")

    assert cache.get(f"dashboard:seeker:{seeker.pk}") is not None


def test_a_dashboard_is_never_stored_by_the_browser(seeker, django_user_model):
    """
    Regression: the response carried "private, max-age=30". A browser keys its
    cache on the URL, not on who asked, so after a logout and a login on the
    same machine the next person was served the previous person's dashboard -
    their name, their applications, their offers - for half a minute.
    """
    client = APIClient()
    client.force_authenticate(seeker)

    response = client.get("/api/v1/dashboard/me/")

    assert response.status_code == 200
    cache_control = response["Cache-Control"]
    assert "no-store" in cache_control
    assert "max-age" not in cache_control


def test_no_per_user_endpoint_lets_the_browser_keep_it(seeker, django_user_model):
    """The same reasoning covers every dashboard response, not just the first."""
    recruiter_user = django_user_model.objects.create_user(
        email="cache-recruiter@test.com",
        password="pw-12345678",
        role="recruiter",
        is_email_verified=True,
    )
    checks = [(seeker, "/api/v1/dashboard/me/"), (recruiter_user, "/api/v1/dashboard/recruiter/")]

    for user, url in checks:
        client = APIClient()
        client.force_authenticate(user)
        response = client.get(url)
        if response.status_code != 200:
            continue  # plan-gated endpoints are covered by their own tests
        assert "max-age" not in response["Cache-Control"], url
