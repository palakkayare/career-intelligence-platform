"""
Throttle configuration and behaviour.
"""
import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.throttles import ApplyThrottle, SearchThrottle

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """Throttle counters live in the cache and would leak between tests."""
    cache.clear()
    yield
    cache.clear()


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_blueprint_throttle_rates_are_configured():
    """
    Regression: Phase 3 asks for "Search (60/min), Apply (20/hr) per user"
    and neither scope existed in DEFAULT_THROTTLE_RATES.
    """
    from django.conf import settings

    rates = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
    assert 'search' in rates
    assert 'apply' in rates


def test_throttle_scopes():
    assert SearchThrottle.scope == 'search'
    assert ApplyThrottle.scope == 'apply'


@pytest.mark.parametrize('view_path,throttle_name', [
    ('apps.jobs.views.JobSearchView', 'SearchThrottle'),
    ('apps.jobs.views.PublicJobListView', 'SearchThrottle'),
    ('apps.applications.views.ApplyToJobView', 'ApplyThrottle'),
    ('apps.recruiters.candidate_views.CandidateSearchView', 'SearchThrottle'),
])
def test_expensive_views_are_throttled(view_path, throttle_name):
    import importlib

    module_path, class_name = view_path.rsplit('.', 1)
    view = getattr(importlib.import_module(module_path), class_name)

    assert any(
        t.__name__ == throttle_name for t in view.throttle_classes
    ), f'{class_name} should carry {throttle_name}'


def test_every_throttle_scope_has_a_rate():
    """A scope with no rate raises ImproperlyConfigured at request time."""
    from django.conf import settings

    from apps.accounts import throttles as auth_throttles
    from apps.payments.views import SubscriptionThrottle

    rates = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
    scopes = {
        SearchThrottle.scope,
        ApplyThrottle.scope,
        SubscriptionThrottle.scope,
        auth_throttles.LoginThrottle.scope,
        auth_throttles.RegisterThrottle.scope,
        auth_throttles.PasswordResetThrottle.scope,
        auth_throttles.OTPRequestThrottle.scope,
        auth_throttles.TwoFAThrottle.scope,
    }

    assert scopes <= set(rates), f'missing rates for {scopes - set(rates)}'


# --------------------------------------------------------------------------
# Behaviour
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Behaviour
# --------------------------------------------------------------------------

# DRF resolves THROTTLE_RATES once, into a class attribute on
# SimpleRateThrottle, so override_settings never reaches it. Patching the
# dict directly is what actually changes the limit for a test.
def _tight_limit():
    from unittest.mock import patch
    from rest_framework.throttling import SimpleRateThrottle

    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'search': '2/min'})


def test_search_returns_429_once_the_limit_is_hit(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)

    with _tight_limit():
        assert client.get('/api/v1/jobs/search/?q=python').status_code == 200
        assert client.get('/api/v1/jobs/search/?q=python').status_code == 200

        blocked = client.get('/api/v1/jobs/search/?q=python')

    assert blocked.status_code == 429


def test_the_limit_is_per_user_not_global(seeker_user, recruiter_user):
    """One user burning through their quota must not block anyone else."""
    first = APIClient()
    first.force_authenticate(user=seeker_user)

    second = APIClient()
    second.force_authenticate(user=recruiter_user)

    with _tight_limit():
        for _ in range(3):
            first.get('/api/v1/jobs/search/?q=python')

        assert first.get('/api/v1/jobs/search/?q=python').status_code == 429
        assert second.get('/api/v1/jobs/search/?q=python').status_code == 200