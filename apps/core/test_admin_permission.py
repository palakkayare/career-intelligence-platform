"""
One rule decides who is a platform admin.

Regression: job approval checked `role == "admin"`, while review moderation
and the admin dashboards checked Django's `is_staff`. An admin created
without the Django flag could approve jobs but got 403 everywhere else.
"""

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ADMIN_URLS = [
    "/api/v1/admin/jobs/pending/",
    "/api/v1/reviews/moderation/queue/",
    "/api/v1/admin/dashboard/",
]


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def plain_admin(django_user_model):
    """role=admin, but none of Django's flags."""
    return django_user_model.objects.create_user(
        email="platform-admin@example.com", password="pw-12345678", role="admin"
    )


@pytest.mark.parametrize("url", ADMIN_URLS)
def test_an_admin_reaches_every_admin_area(plain_admin, url):
    assert plain_admin.is_staff is False
    assert client_for(plain_admin).get(url).status_code == 200


@pytest.mark.parametrize("url", ADMIN_URLS)
def test_a_seeker_reaches_none_of_them(django_user_model, url):
    seeker = django_user_model.objects.create_user(
        email="not-admin@example.com", password="pw-12345678", role="seeker"
    )
    assert client_for(seeker).get(url).status_code == 403


@pytest.mark.parametrize("url", ADMIN_URLS)
def test_a_recruiter_reaches_none_of_them(django_user_model, url):
    recruiter = django_user_model.objects.create_user(
        email="rec-not-admin@example.com", password="pw-12345678", role="recruiter"
    )
    assert client_for(recruiter).get(url).status_code == 403


@pytest.mark.parametrize("url", ADMIN_URLS)
def test_a_superuser_still_counts(django_user_model, url):
    root = django_user_model.objects.create_superuser(
        email="root@example.com", password="pw-12345678"
    )
    assert client_for(root).get(url).status_code == 200


@pytest.mark.parametrize("url", ADMIN_URLS)
def test_anonymous_is_refused(url):
    assert APIClient().get(url).status_code == 401
