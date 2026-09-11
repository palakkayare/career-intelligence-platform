"""
The deliberate error used to check Sentry after a deploy.
"""

import pytest
from rest_framework.test import APIClient

from apps.core.views import SentryTestError

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/dashboard/sentry-test/"


@pytest.fixture
def staff_client():
    from apps.accounts.models import User

    admin = User.objects.create_superuser(email="ops@test.com", password="TestPass123!")
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


def test_anonymous_users_cannot_trigger_it():
    assert APIClient().post(URL).status_code in (401, 403)


def test_regular_users_cannot_trigger_it(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)

    assert client.post(URL).status_code == 403


def test_a_get_never_raises(staff_client):
    """A crawler or link preview must not be able to fire it."""
    assert staff_client.get(URL).status_code == 405


def test_staff_post_raises_an_unhandled_error(staff_client):
    with pytest.raises(SentryTestError):
        staff_client.post(URL)
