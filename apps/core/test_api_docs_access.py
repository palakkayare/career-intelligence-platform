"""
Who can reach the API documentation.

Regression: production allowed only staff but authenticated with JWT alone,
so a browser session from /admin/ was ignored and even a superuser got 401 -
the docs were unreachable in the only way anyone would open them.

drf-spectacular reads SERVE_PERMISSIONS and SERVE_AUTHENTICATION into class
attributes when its views are imported, so override_settings cannot change
them afterwards. These tests build the view with the configured
authentication classes instead, and set request.user the way Django's
authentication middleware does after a session login.
"""

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import reverse
from django.utils.module_loading import import_string
from drf_spectacular.views import SpectacularAPIView
from rest_framework.permissions import IsAdminUser
from rest_framework.test import APIRequestFactory

pytestmark = pytest.mark.django_db


def configured_authentication():
    return [import_string(path) for path in settings.SPECTACULAR_SETTINGS["SERVE_AUTHENTICATION"]]


def as_production(user):
    """The schema view as production serves it: staff only."""
    view = SpectacularAPIView.as_view(
        authentication_classes=configured_authentication(),
        permission_classes=[IsAdminUser],
    )
    request = APIRequestFactory().get("/api/schema/")
    request.user = user
    return view(request).status_code


@pytest.mark.regression
def test_session_authentication_is_configured():
    """
    A browser has a cookie, not a bearer token. Without this class the docs
    ignore a signed-in admin entirely.
    """
    from rest_framework.authentication import SessionAuthentication

    assert SessionAuthentication in configured_authentication()


@pytest.mark.regression
def test_a_signed_in_admin_reaches_the_docs():
    from apps.accounts.models import User

    admin = User.objects.create_superuser(email="ops@test.com", password="TestPass123!")

    assert as_production(admin) == 200


def test_anonymous_visitors_are_refused():
    assert as_production(AnonymousUser()) == 403


def test_a_signed_in_seeker_is_refused(seeker_user):
    """Staff only: the endpoint list should not be handed to every user."""
    assert as_production(seeker_user) == 403


@pytest.mark.parametrize("name", ["schema", "docs"])
def test_locally_the_docs_are_open(name):
    """No login at all while developing, or the frontend work stalls."""
    assert Client().get(reverse(name)).status_code == 200
