"""
A seeker's comparison carries their own salary, and nobody else's.

Regression: the page drew "You" at the market median because the response
had no number for the person; everyone appeared exactly average.
"""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.career_intel.models import SalarySubmission
from apps.payments.models import Plan, Subscription

pytestmark = pytest.mark.django_db

URL = "/api/v1/salary/my-comparison/"


@pytest.fixture
def seeker(django_user_model):
    user = django_user_model.objects.create_user(
        email="salary-me@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )
    plan = Plan.objects.create(
        name="Pro", slug="pro-sal", tier="pro", price_inr=499, has_salary_insights=True
    )
    now = timezone.now()
    Subscription.objects.create(
        user=user,
        plan=plan,
        status="active",
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=20),
    )
    return user


def submission(user, salary, **extra):
    base = dict(
        user=user,
        role_title="Backend Developer",
        location_city="Pune",
        experience_years_bucket="2-5",
        company_size_bucket="medium",
        employment_type="full_time",
        work_arrangement="hybrid",
        salary_inr=salary,
        effective_year=timezone.now().year,
    )
    base.update(extra)
    return SalarySubmission.objects.create(**base)


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_without_a_submission_the_message_is_for_people(seeker):
    body = client_for(seeker).get(URL).json()
    assert body["has_submission"] is False
    assert "/salary/" not in body["message"]


@override_settings(SALARY_K_ANONYMITY=5)
def test_not_enough_data_still_returns_my_own_figure(seeker):
    submission(seeker, 1_850_000)
    body = client_for(seeker).get(URL).json()
    assert body["has_market_data"] is False
    assert body["your_submission"]["salary_inr"] == 1_850_000
    assert body["your_submission"]["salary_lpa"] == "₹18.5 LPA"


@override_settings(SALARY_K_ANONYMITY=5)
def test_full_comparison_returns_my_figure_and_only_aggregates(seeker, django_user_model):
    submission(seeker, 2_000_000)
    others = [900_000, 1_200_000, 1_500_000, 1_800_000, 2_600_000]
    for i, salary in enumerate(others):
        other = django_user_model.objects.create_user(
            email=f"peer{i}@example.com", password="pw-12345678", role="seeker"
        )
        submission(other, salary)

    body = client_for(seeker).get(URL).json()

    assert body["has_market_data"] is True
    assert body["your_submission"]["salary_inr"] == 2_000_000
    published = body["market_insights"]["salary_range_inr"]
    assert set(published) == {"p25", "median", "p75", "mean"}
    for value in others:
        assert value not in published.values()


@override_settings(SALARY_K_ANONYMITY=5)
def test_the_message_quotes_only_published_figures(seeker, django_user_model):
    """
    Regression: the message quoted the unrounded median - with a handful of
    submissions that is one person's exact salary - and it disagreed with the
    rounded median shown beside it.
    """
    submission(seeker, 1_950_000)
    peers = [900_000, 1_200_000, 1_450_000, 1_600_000, 2_100_000, 2_400_000]
    for i, salary in enumerate(peers):
        other = django_user_model.objects.create_user(
            email=f"msg-peer{i}@example.com", password="pw-12345678", role="seeker"
        )
        submission(other, salary)

    body = client_for(seeker).get(URL).json()
    message = body["message"]
    published_median = body["market_insights"]["salary_range_inr"]["median"]

    for salary in peers:
        assert f"₹{salary / 100000:.1f}L" not in message
    assert f"₹{published_median / 100000:.1f}L" in message


def test_top_of_market_message_has_no_figure():
    from apps.career_intel.salary_algorithm import market_position_message

    text = market_position_message(
        "top_of_market", 5_000_000, {"median": 1_500_000, "p75": 2_000_000}
    )
    assert "₹" not in text
