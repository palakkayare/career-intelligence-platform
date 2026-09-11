"""
The release and settings the running app reports after a deploy or rollback.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/dashboard/deploy-info/"


@pytest.fixture
def staff_client():
    from apps.accounts.models import User

    admin = User.objects.create_superuser(email="ops@test.com", password="TestPass123!")
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


def test_anonymous_users_are_refused():
    assert APIClient().get(URL).status_code in (401, 403)


def test_non_staff_users_are_refused(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)

    assert client.get(URL).status_code == 403


@override_settings(
    SENTRY_RELEASE="97e622e1234",
    SENTRY_ENVIRONMENT="production",
    TRUSTED_PROXY_COUNT=2,
    RAZORPAY_KEY_ID="rzp_test_abc",
    AWS_S3_USE_S3=True,
    SENTRY_DSN="https://key@o1.ingest.sentry.io/1",
)
def test_it_reports_the_settings_in_force(staff_client):
    response = staff_client.get(URL)

    assert response.status_code == 200
    assert response.data == {
        "release": "97e622e1234",
        "environment": "production",
        "trusted_proxy_count": 2,
        "razorpay_mode": "test",
        "s3_uploads": True,
        "sentry_enabled": True,
    }


@pytest.mark.parametrize(
    "key, mode",
    [("rzp_live_abc", "live"), ("rzp_test_abc", "test"), ("", "not configured")],
)
def test_razorpay_mode_never_exposes_the_key(staff_client, key, mode):
    with override_settings(RAZORPAY_KEY_ID=key):
        response = staff_client.get(URL)

    assert response.data["razorpay_mode"] == mode
    assert "abc" not in str(response.data)
