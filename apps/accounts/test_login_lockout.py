"""
Step 32: client IPs that cannot be forged, and login lockout.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from apps.accounts.lockout import LoginLockoutService
from apps.accounts.models import LoginHistory
from apps.core.client_ip import client_ip

LOGIN_URL = "/api/v1/auth/login/"
PASSWORD = "Correct-Horse-Battery-9!"
ATTACKER_IP = "203.0.113.7"

rf = RequestFactory()


# --------------------------------------------------------------------------
# Client IP
# --------------------------------------------------------------------------


def test_by_default_the_forwarded_header_is_not_trusted(settings):
    """Without a known proxy in front, the header is whatever the client typed."""
    settings.TRUSTED_PROXY_COUNT = 0
    request = rf.get("/", REMOTE_ADDR="198.51.100.1", HTTP_X_FORWARDED_FOR="1.2.3.4")

    assert client_ip(request) == "198.51.100.1"


def test_behind_one_proxy_the_address_it_appended_is_used(settings):
    settings.TRUSTED_PROXY_COUNT = 1
    request = rf.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="1.2.3.4, 198.51.100.9")

    assert client_ip(request) == "198.51.100.9", "the client-typed 1.2.3.4 is ignored"


def test_behind_two_proxies_the_second_from_the_right_is_used(settings):
    settings.TRUSTED_PROXY_COUNT = 2
    request = rf.get(
        "/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6, 198.51.100.9, 172.16.0.2"
    )

    assert client_ip(request) == "198.51.100.9"


def test_a_malformed_forwarded_value_falls_back_instead_of_crashing(settings):
    """Regression: a junk header reached the inet column and failed the request."""
    settings.TRUSTED_PROXY_COUNT = 1
    request = rf.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="not-an-ip")

    assert client_ip(request) == "10.0.0.1"


def test_throttling_uses_the_same_proxy_count():
    """Rate limits and lockout must agree on who the client is."""
    assert api_settings.NUM_PROXIES == settings.TRUSTED_PROXY_COUNT


# --------------------------------------------------------------------------
# Lockout
# --------------------------------------------------------------------------


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(email="lockout@test.com", password=PASSWORD)


@pytest.fixture
def client():
    return APIClient()


def login(client, email, password, ip=ATTACKER_IP, **extra):
    return client.post(
        LOGIN_URL, {"email": email, "password": password}, format="json", REMOTE_ADDR=ip, **extra
    )


def fail(client, email, times, ip=ATTACKER_IP):
    for _ in range(times):
        assert login(client, email, "wrong-password", ip=ip).status_code == 401


def test_five_failures_lock_out_even_the_right_password(client, user):
    fail(client, user.email, 5)

    response = login(client, user.email, PASSWORD)

    assert response.status_code == 429
    assert "access" not in response.data
    assert 0 < int(response["Retry-After"]) <= 15 * 60


def test_four_failures_do_not(client, user):
    fail(client, user.email, 4)

    assert login(client, user.email, PASSWORD).status_code == 200


def test_refused_attempts_are_not_recorded_so_the_lock_ends_on_time(client, user):
    fail(client, user.email, 5)
    for _ in range(3):
        login(client, user.email, "still-guessing")

    assert LoginHistory.objects.filter(status=LoginHistory.Status.FAILED).count() == 5


def test_nobody_can_lock_the_owner_out_from_another_address(client, user):
    """Keyed on email alone, five bad guesses from anywhere would shut the owner out."""
    fail(client, user.email, 5, ip=ATTACKER_IP)

    assert login(client, user.email, PASSWORD, ip="198.51.100.20").status_code == 200


def test_a_forged_forwarded_header_does_not_escape_the_lock(client, user):
    fail(client, user.email, 5)

    response = login(client, user.email, PASSWORD, HTTP_X_FORWARDED_FOR="9.9.9.9")

    assert response.status_code == 429


def test_a_lock_says_nothing_about_whether_the_account_exists(client, user):
    fail(client, user.email, 5)
    fail(client, "nobody-here@test.com", 5)

    real = login(client, user.email, "x")
    fake = login(client, "nobody-here@test.com", "x")

    assert real.status_code == fake.status_code == 429
    assert real.data == fake.data


def test_the_lock_expires_after_the_window(client, user):
    fail(client, user.email, 5)
    LoginHistory.objects.update(created_at=timezone.now() - timedelta(minutes=16))

    assert login(client, user.email, PASSWORD).status_code == 200


def test_a_successful_login_resets_the_count(client, user):
    fail(client, user.email, 4)
    assert login(client, user.email, PASSWORD).status_code == 200

    fail(client, user.email, 4)

    assert login(client, user.email, PASSWORD).status_code == 200


def test_email_case_does_not_split_the_count(client, user):
    fail(client, "LOCKOUT@test.com", 5)

    assert login(client, user.email, PASSWORD).status_code == 429


def test_the_threshold_is_configurable(settings, client, user):
    settings.LOGIN_LOCKOUT_THRESHOLD = 2
    fail(client, user.email, 2)

    assert login(client, user.email, PASSWORD).status_code == 429


@pytest.mark.django_db
def test_seconds_remaining_counts_down_from_the_oldest_failure_in_the_window():
    now = timezone.now()
    for minutes_ago in (1, 2, 3, 4, 10):
        entry = LoginHistory.objects.create(
            email_attempted="a@test.com", status=LoginHistory.Status.FAILED, ip_address=ATTACKER_IP
        )
        LoginHistory.objects.filter(pk=entry.pk).update(
            created_at=now - timedelta(minutes=minutes_ago)
        )

    remaining = LoginLockoutService.seconds_remaining("a@test.com", ATTACKER_IP)

    assert 4 * 60 < remaining <= 5 * 60
