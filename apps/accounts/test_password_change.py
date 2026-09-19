"""
POST /api/v1/auth/password/change/, and sessions ending with a new password.

Regression: there was no way to change a password while signed in, and a
password reset left every existing session alive - including the one
belonging to whoever the reset was meant to lock out.
"""

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db

URL = "/api/v1/auth/password/change/"
OLD = "Old-pass-9x!"
NEW = "Brand-new-7q!"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="changer@example.com", password=OLD, role="seeker", is_email_verified=True
    )


def as_user(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def body(current=OLD, new=NEW, confirm=None):
    return {
        "current_password": current,
        "new_password": new,
        "new_password_confirm": confirm or new,
    }


def test_changes_the_password_and_keeps_this_device_signed_in(user):
    response = as_user(user).post(URL, body())

    assert response.status_code == 200, response.content
    user.refresh_from_db()
    assert user.check_password(NEW)
    data = response.json()
    assert data["access"] and data["refresh"]
    # the new refresh token is not the one that got blacklisted
    assert not BlacklistedToken.objects.filter(
        token__jti=RefreshToken(data["refresh"])["jti"]
    ).exists()


def test_signs_out_every_other_session(user):
    laptop = RefreshToken.for_user(user)
    phone = RefreshToken.for_user(user)

    as_user(user).post(URL, body())

    blacklisted = set(BlacklistedToken.objects.values_list("token__jti", flat=True))
    assert {laptop["jti"], phone["jti"]} <= blacklisted
    refresh = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": str(laptop)})
    assert refresh.status_code == 401


def test_requires_the_current_password(user):
    response = as_user(user).post(URL, body(current="wrong-one"))
    assert response.status_code == 400
    assert "current_password" in response.json()
    user.refresh_from_db()
    assert user.check_password(OLD)


def test_rejects_a_mismatch_a_reuse_and_a_weak_password(user):
    client = as_user(user)
    assert "new_password_confirm" in client.post(URL, body(confirm="Other-pass-1!")).json()
    assert "new_password" in client.post(URL, body(new=OLD)).json()
    weak = client.post(URL, body(new="12345678"))
    assert weak.status_code == 400


def test_an_account_without_a_password_is_pointed_at_reset(django_user_model):
    google_user = django_user_model.objects.create_user(
        email="google-only@example.com", password=None, role="seeker"
    )
    google_user.set_unusable_password()
    google_user.save()

    response = as_user(google_user).post(URL, body())

    assert response.status_code == 400
    assert "Forgot password" in response.json()["current_password"][0]


def test_anonymous_is_rejected():
    assert APIClient().post(URL, body()).status_code == 401


def test_a_password_reset_also_ends_existing_sessions(user):
    stolen = RefreshToken.for_user(user)
    response = APIClient().post(
        "/api/v1/auth/password/reset/confirm/",
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user),
            "new_password": NEW,
            "new_password_confirm": NEW,
        },
    )
    assert response.status_code == 200, response.content
    assert BlacklistedToken.objects.filter(token__jti=stolen["jti"]).exists()
