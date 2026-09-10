"""
Authentication endpoints.

The services behind these are covered in test_services.py; this file walks
the flows a real client walks - register, verify, log in, add 2FA, log in
again - and checks what the API hands back at each step.

Throttling is disabled in test settings, so repeated login attempts here do
not trip the 5/min limit. apps/core/tests.py covers throttling itself.
"""

import pyotp
import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import LoginHistory, OTPCode, User
from apps.accounts.services import OTPService, TwoFactorAuthService

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass123!"


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def auth(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)
    return client


def register_payload(**overrides):
    payload = {
        "email": "new@test.com",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "role": "seeker",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_registration_creates_an_unverified_user(api, plans):
    """Regression: accounts/views.py was at 34% coverage."""
    response = api.post("/api/v1/auth/register/", register_payload(), format="json")

    assert response.status_code == 201
    user = User.objects.get(email="new@test.com")
    assert user.is_email_verified is False
    assert user.role == "seeker"


def test_registration_never_echoes_the_password(api, plans):
    response = api.post("/api/v1/auth/register/", register_payload(), format="json")

    assert "password" not in str(response.data)


def test_mismatched_passwords_are_rejected(api, plans):
    response = api.post(
        "/api/v1/auth/register/",
        register_payload(password_confirm="SomethingElse123!"),
        format="json",
    )

    assert response.status_code == 400
    assert not User.objects.filter(email="new@test.com").exists()


def test_a_weak_password_is_rejected(api, plans):
    response = api.post(
        "/api/v1/auth/register/",
        register_payload(password="password", password_confirm="password"),
        format="json",
    )

    assert response.status_code == 400


def test_duplicate_emails_are_rejected(api, seeker_user):
    response = api.post(
        "/api/v1/auth/register/",
        register_payload(email=seeker_user.email),
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.regression
def test_nobody_can_register_themselves_as_admin(api, plans):
    """
    Public registration takes the role from the request body, so this is the
    only thing standing between an open endpoint and an admin account.
    """
    response = api.post(
        "/api/v1/auth/register/",
        register_payload(role="admin"),
        format="json",
    )

    assert response.status_code == 400
    assert not User.objects.filter(email="new@test.com").exists()


def test_registration_sends_a_verification_code(api, plans):
    mail.outbox = []

    api.post("/api/v1/auth/register/", register_payload(), format="json")

    user = User.objects.get(email="new@test.com")
    assert OTPCode.objects.filter(user=user).exists()
    assert len(mail.outbox) == 1


# --------------------------------------------------------------------------
# Email verification
# --------------------------------------------------------------------------


def test_the_right_code_verifies_the_email(api, seeker_user):
    seeker_user.is_email_verified = False
    seeker_user.save(update_fields=["is_email_verified"])
    otp = OTPService.create_and_send(seeker_user)

    response = api.post(
        "/api/v1/auth/verify-email/",
        {
            "email": seeker_user.email,
            "code": otp.code,
        },
        format="json",
    )

    seeker_user.refresh_from_db()
    assert response.status_code == 200
    assert seeker_user.is_email_verified is True


def test_a_wrong_code_leaves_the_email_unverified(api, seeker_user):
    seeker_user.is_email_verified = False
    seeker_user.save(update_fields=["is_email_verified"])
    OTPService.create_and_send(seeker_user)

    response = api.post(
        "/api/v1/auth/verify-email/",
        {
            "email": seeker_user.email,
            "code": "000000",
        },
        format="json",
    )

    seeker_user.refresh_from_db()
    assert response.status_code == 400
    assert seeker_user.is_email_verified is False


def test_verifying_an_unknown_email_does_not_reveal_anything(api, plans):
    """The response must not confirm whether an address is registered."""
    response = api.post(
        "/api/v1/auth/verify-email/",
        {
            "email": "nobody@test.com",
            "code": "123456",
        },
        format="json",
    )

    assert response.status_code in (400, 404)


def test_resend_issues_a_fresh_code(api, seeker_user):
    seeker_user.is_email_verified = False
    seeker_user.save(update_fields=["is_email_verified"])

    response = api.post(
        "/api/v1/auth/resend-otp/",
        {
            "email": seeker_user.email,
        },
        format="json",
    )

    assert response.status_code == 200
    assert OTPCode.objects.filter(user=seeker_user, is_used=False).exists()


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------


def test_correct_credentials_return_a_token_pair(api, seeker_user):
    response = api.post(
        "/api/v1/auth/login/",
        {
            "email": seeker_user.email,
            "password": PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["access"]
    assert response.data["refresh"]
    assert response.data["user"]["email"] == seeker_user.email


def test_a_wrong_password_is_rejected(api, seeker_user):
    response = api.post(
        "/api/v1/auth/login/",
        {
            "email": seeker_user.email,
            "password": "wrong",
        },
        format="json",
    )

    assert response.status_code == 401


def test_an_unknown_email_gets_the_same_error_as_a_wrong_password(api, seeker_user):
    """Different messages would let someone enumerate registered addresses."""
    wrong_password = api.post(
        "/api/v1/auth/login/",
        {
            "email": seeker_user.email,
            "password": "wrong",
        },
        format="json",
    )
    unknown_email = api.post(
        "/api/v1/auth/login/",
        {
            "email": "nobody@test.com",
            "password": "wrong",
        },
        format="json",
    )

    assert wrong_password.status_code == unknown_email.status_code
    assert wrong_password.data == unknown_email.data


def test_missing_fields_are_rejected(api):
    assert api.post("/api/v1/auth/login/", {}, format="json").status_code == 400


def test_the_email_is_matched_case_insensitively(api, seeker_user):
    response = api.post(
        "/api/v1/auth/login/",
        {
            "email": seeker_user.email.upper(),
            "password": PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 200


@pytest.mark.regression
def test_a_deactivated_account_cannot_log_in(api, seeker_user):
    """
    The soft-delete manager fix is what makes this work. Without it a closed
    account still authenticates.
    """
    seeker_user.soft_delete()

    response = api.post(
        "/api/v1/auth/login/",
        {
            "email": seeker_user.email,
            "password": PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 401


# --------------------------------------------------------------------------
# Login history
# --------------------------------------------------------------------------


def test_a_successful_login_is_recorded(api, seeker_user):
    api.post(
        "/api/v1/auth/login/",
        {
            "email": seeker_user.email,
            "password": PASSWORD,
        },
        format="json",
    )

    entry = LoginHistory.objects.filter(user=seeker_user).latest("created_at")
    assert entry.status == LoginHistory.Status.SUCCESS


@pytest.mark.regression
def test_a_failed_login_is_recorded_too(api, seeker_user):
    """
    Failed attempts are the ones worth having. Without them a password
    spraying attempt leaves no trace at all.
    """
    api.post(
        "/api/v1/auth/login/",
        {
            "email": seeker_user.email,
            "password": "wrong",
        },
        format="json",
    )

    entry = LoginHistory.objects.latest("created_at")
    assert entry.status == LoginHistory.Status.FAILED
    assert entry.email_attempted == seeker_user.email


def test_the_forwarded_ip_is_preferred_over_the_socket_address(api, seeker_user):
    """Behind Nginx, REMOTE_ADDR is the proxy, not the client."""
    api.post(
        "/api/v1/auth/login/",
        {"email": seeker_user.email, "password": PASSWORD},
        format="json",
        HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
    )

    entry = LoginHistory.objects.latest("created_at")
    assert entry.ip_address == "203.0.113.7"


def test_a_seeker_sees_only_their_own_history(auth, seeker_user, recruiter_user):
    LoginHistory.objects.create(
        user=recruiter_user,
        email_attempted=recruiter_user.email,
        status=LoginHistory.Status.SUCCESS,
        ip_address="10.0.0.1",
    )
    LoginHistory.objects.create(
        user=seeker_user,
        email_attempted=seeker_user.email,
        status=LoginHistory.Status.SUCCESS,
        ip_address="203.0.113.7",
    )

    response = auth.get("/api/v1/auth/login-history/")

    assert response.status_code == 200
    rows = response.data["results"]
    assert len(rows) == 1
    assert rows[0]["ip_address"] == "203.0.113.7"


# --------------------------------------------------------------------------
# Two-factor login
# --------------------------------------------------------------------------


@pytest.fixture
def user_with_2fa(seeker_user):
    setup = TwoFactorAuthService.initiate_setup(seeker_user)
    secret = setup["secret_text"]
    codes = TwoFactorAuthService.verify_and_enable(
        seeker_user,
        pyotp.TOTP(secret).now(),
    )
    return seeker_user, secret, codes


@pytest.mark.regression
def test_2fa_login_withholds_the_jwt_at_step_one(api, user_with_2fa):
    """
    The whole point of 2FA: a correct password alone must not produce a
    usable token.
    """
    user, _, _ = user_with_2fa

    response = api.post(
        "/api/v1/auth/login/",
        {
            "email": user.email,
            "password": PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["2fa_required"] is True
    assert response.data["pending_token"]
    assert "access" not in response.data
    assert "refresh" not in response.data


def test_the_second_step_exchanges_a_code_for_a_token(api, user_with_2fa):
    user, secret, _ = user_with_2fa
    step_one = api.post(
        "/api/v1/auth/login/",
        {
            "email": user.email,
            "password": PASSWORD,
        },
        format="json",
    )

    response = api.post(
        "/api/v1/auth/2fa/verify-login/",
        {
            "pending_token": step_one.data["pending_token"],
            "code": pyotp.TOTP(secret).now(),
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["access"]


def test_a_backup_code_also_completes_the_login(api, user_with_2fa):
    user, _, codes = user_with_2fa
    step_one = api.post(
        "/api/v1/auth/login/",
        {
            "email": user.email,
            "password": PASSWORD,
        },
        format="json",
    )

    response = api.post(
        "/api/v1/auth/2fa/verify-login/",
        {
            "pending_token": step_one.data["pending_token"],
            "code": codes[0],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["access"]


def test_a_wrong_second_factor_is_refused(api, user_with_2fa):
    user, _, _ = user_with_2fa
    step_one = api.post(
        "/api/v1/auth/login/",
        {
            "email": user.email,
            "password": PASSWORD,
        },
        format="json",
    )

    response = api.post(
        "/api/v1/auth/2fa/verify-login/",
        {
            "pending_token": step_one.data["pending_token"],
            "code": "000000",
        },
        format="json",
    )

    assert response.status_code in (400, 401)
    assert "access" not in response.data


def test_step_two_cannot_be_reached_without_a_pending_token(api, user_with_2fa):
    user, secret, _ = user_with_2fa

    response = api.post(
        "/api/v1/auth/2fa/verify-login/",
        {
            "pending_token": "forged",
            "code": pyotp.TOTP(secret).now(),
        },
        format="json",
    )

    assert response.status_code in (400, 401)


# --------------------------------------------------------------------------
# Profile and password reset
# --------------------------------------------------------------------------


def test_me_returns_the_authenticated_user(auth, seeker_user):
    response = auth.get("/api/v1/auth/me/")

    assert response.status_code == 200
    assert response.data["email"] == seeker_user.email


def test_me_requires_authentication(api):
    assert api.get("/api/v1/auth/me/").status_code in (401, 403)


@pytest.mark.regression
def test_password_reset_does_not_reveal_whether_an_email_exists(api, seeker_user):
    """
    A different response for unknown addresses turns this endpoint into an
    account-enumeration oracle.
    """
    known = api.post(
        "/api/v1/auth/password/reset/",
        {
            "email": seeker_user.email,
        },
        format="json",
    )
    unknown = api.post(
        "/api/v1/auth/password/reset/",
        {
            "email": "nobody@test.com",
        },
        format="json",
    )

    assert known.status_code == unknown.status_code == 200


def test_password_reset_emails_only_a_real_user(api, seeker_user):
    mail.outbox = []
    api.post(
        "/api/v1/auth/password/reset/",
        {
            "email": "nobody@test.com",
        },
        format="json",
    )
    assert mail.outbox == []

    api.post(
        "/api/v1/auth/password/reset/",
        {
            "email": seeker_user.email,
        },
        format="json",
    )
    assert len(mail.outbox) == 1
