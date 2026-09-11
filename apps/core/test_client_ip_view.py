"""
The client-ip diagnostic used to set TRUSTED_PROXY_COUNT after a deploy.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/dashboard/client-ip/"


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


@override_settings(TRUSTED_PROXY_COUNT=2)
def test_it_shows_the_headers_and_the_address_chosen(staff_client):
    """Cloudflare then Railway: client, Cloudflare edge. Two proxies."""
    response = staff_client.get(
        URL,
        HTTP_X_FORWARDED_FOR="203.0.113.7, 172.70.1.1",
        HTTP_CF_CONNECTING_IP="203.0.113.7",
        REMOTE_ADDR="10.0.0.5",
    )

    assert response.status_code == 200
    assert response.data == {
        "remote_addr": "10.0.0.5",
        "x_forwarded_for": "203.0.113.7, 172.70.1.1",
        "cf_connecting_ip": "203.0.113.7",
        "trusted_proxy_count": 2,
        "resolved_client_ip": "203.0.113.7",
    }


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_a_wrong_count_is_visible(staff_client):
    """Count 1 behind two proxies picks the Cloudflare edge, and says so."""
    response = staff_client.get(
        URL,
        HTTP_X_FORWARDED_FOR="203.0.113.7, 172.70.1.1",
        REMOTE_ADDR="10.0.0.5",
    )

    assert response.data["resolved_client_ip"] == "172.70.1.1"
