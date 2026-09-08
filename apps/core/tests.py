"""
Throttle configuration and behaviour.
"""
import pytest
from django.core.cache import cache
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


# --------------------------------------------------------------------------
# Admin dashboard metrics
# --------------------------------------------------------------------------

from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from apps.core.metrics import ActivityMetrics, RevenueMetrics, dashboard_snapshot


@pytest.fixture
def paid_subscriber(free_seeker, plans):
    """A seeker on an active paid Pro plan."""
    from apps.payments.models import Subscription

    sub = free_seeker.user.subscriptions.order_by('-created_at').first()
    sub.plan = plans['pro']
    sub.status = Subscription.Status.ACTIVE
    sub.trial_ends_at = None
    sub.current_period_start = timezone.now() - timedelta(days=5)
    sub.current_period_end = timezone.now() + timedelta(days=25)
    sub.save()
    return free_seeker.user


@pytest.mark.regression
def test_mrr_counts_active_paid_subscriptions(paid_subscriber, plans):
    """
    Regression: Feature 10 asks for a revenue dashboard with MRR, churn and
    active plans. None of it existed.
    """
    assert RevenueMetrics.mrr() == Decimal('499.00')
    assert RevenueMetrics.arr() == Decimal('5988.00')
    assert RevenueMetrics.active_paid_subscriptions().count() == 1


def test_trials_do_not_count_towards_mrr(seeker_user):
    """A trial pays nothing, so it must not inflate recurring revenue."""
    assert seeker_user.subscriptions.get().status == 'trialing'
    assert RevenueMetrics.mrr() == Decimal('0.00')


def test_yearly_plans_are_spread_across_the_year(free_seeker, plans):
    from apps.payments.models import Plan, Subscription

    yearly = Plan.objects.create(
        name='Pro Yearly', slug='pro_yearly', tier=Plan.Tier.PRO,
        billing_period=Plan.BillingPeriod.YEARLY, price_inr=Decimal('4790'),
    )
    sub = free_seeker.user.subscriptions.order_by('-created_at').first()
    sub.plan = yearly
    sub.status = Subscription.Status.ACTIVE
    sub.trial_ends_at = None
    sub.current_period_end = timezone.now() + timedelta(days=300)
    sub.save()

    # 4790 / 12, not 4790
    assert RevenueMetrics.mrr() == Decimal('399.17')


def test_expired_subscriptions_drop_out_of_mrr(paid_subscriber):
    sub = paid_subscriber.subscriptions.get()
    sub.current_period_end = timezone.now() - timedelta(days=1)
    sub.save()

    assert RevenueMetrics.mrr() == Decimal('0.00')


def test_a_cancelled_but_unexpired_plan_still_counts(paid_subscriber):
    """Cancellation is graceful: they paid for the period, so they are revenue."""
    from apps.payments.models import Subscription

    sub = paid_subscriber.subscriptions.get()
    sub.status = Subscription.Status.CANCELLED
    sub.cancelled_at = timezone.now()
    sub.save()

    assert RevenueMetrics.mrr() == Decimal('499.00')


def test_churn_is_zero_with_no_cancellations(paid_subscriber):
    assert RevenueMetrics.churn_rate() == Decimal('0.00')


def test_churn_counts_cancellations_against_the_starting_base(paid_subscriber):
    from apps.payments.models import Subscription

    sub = paid_subscriber.subscriptions.get()
    sub.status = Subscription.Status.CANCELLED
    sub.cancelled_at = timezone.now()
    sub.save()

    # One canceller, no survivors -> 100%
    assert RevenueMetrics.churn_rate() == Decimal('100.00')


def test_subscribers_by_plan(paid_subscriber):
    assert RevenueMetrics.subscribers_by_plan() == {'Pro Monthly': 1}


# --------------------------------------------------------------------------
# Activity
# --------------------------------------------------------------------------

def _log_login(user, days_ago=0):
    from apps.accounts.models import LoginHistory

    entry = LoginHistory.objects.create(
        user=user, email_attempted=user.email,
        status=LoginHistory.Status.SUCCESS,
    )
    if days_ago:
        LoginHistory.objects.filter(pk=entry.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago),
        )
    return entry


def test_dau_and_mau(seeker_user, recruiter_user):
    _log_login(seeker_user)                 # today
    _log_login(recruiter_user, days_ago=10)  # this month, not today

    assert ActivityMetrics.dau() == 1
    assert ActivityMetrics.mau() == 2


def test_repeat_logins_count_once(seeker_user):
    _log_login(seeker_user)
    _log_login(seeker_user)
    _log_login(seeker_user)

    assert ActivityMetrics.dau() == 1


def test_failed_logins_are_not_activity(seeker_user):
    from apps.accounts.models import LoginHistory

    LoginHistory.objects.create(
        user=seeker_user, email_attempted=seeker_user.email,
        status=LoginHistory.Status.FAILED,
    )

    assert ActivityMetrics.dau() == 0


def test_applications_per_day_fills_empty_days(seeker, job):
    from apps.applications.services import ApplicationCreationService

    ApplicationCreationService.create(seeker, job)

    series = ActivityMetrics.applications_per_day(days=7)

    assert len(series) == 7
    assert series[-1]['count'] == 1, 'today is last'
    assert all(day['count'] == 0 for day in series[:-1])


def test_withdrawn_applications_stay_in_the_history(seeker, job):
    """Removing them would silently rewrite past days."""
    from apps.applications.models import Application
    from apps.applications.services import (
        ApplicationCreationService, ApplicationStatusService,
    )

    app = ApplicationCreationService.create(seeker, job)
    ApplicationStatusService.update_status(
        app, Application.Status.WITHDRAWN, actor=seeker.user,
    )

    series = ActivityMetrics.applications_per_day(days=7)
    assert series[-1]['count'] == 1


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------

def test_dashboard_snapshot_shape(paid_subscriber):
    snapshot = dashboard_snapshot()

    assert 'revenue' in snapshot and 'activity' in snapshot
    assert snapshot['revenue']['mrr'] == Decimal('499.00')
    assert 'dau' in snapshot['activity']


def test_dashboard_requires_staff(seeker_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=seeker_user)

    assert client.get('/api/v1/admin/dashboard/').status_code == 403


def test_staff_can_read_the_dashboard(plans):
    from rest_framework.test import APIClient

    from apps.accounts.models import User

    admin = User.objects.create_superuser(
        email='ops@test.com', password='TestPass123!',
    )
    client = APIClient()
    client.force_authenticate(user=admin)

    response = client.get('/api/v1/admin/dashboard/')

    assert response.status_code == 200
    assert 'revenue' in response.data