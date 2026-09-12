"""
What a suppressed salary query is allowed to say.

Regression: below the K threshold the response carried the exact number of
matching submissions. That number is the most identifying thing left about a
group too small to publish - 1 rather than 0 confirms a specific person
submitted, and repeating the query with narrower filters maps the population.
"""

from decimal import Decimal

import pytest
from django.test import override_settings

from apps.career_intel.models import SalarySubmission
from apps.career_intel.salary_services import SalaryService

pytestmark = pytest.mark.django_db

LAKH = 100000


def submit(count, salary_lakh=12, **overrides):
    from apps.accounts.models import User

    for index in range(count):
        user = User.objects.create_user(
            email=f"sal{index}-{overrides.get('role_title', 'be')}@test.com",
            password="TestPass123!",
        )
        SalarySubmission.objects.create(
            **{
                "user": user,
                "role_title": "Backend Developer",
                "location_city": "Bengaluru",
                "salary_inr": Decimal(str((salary_lakh + index) * LAKH)),
                "company_size_bucket": SalarySubmission.CompanySizeBucket.MEDIUM,
                "experience_years_bucket": SalarySubmission.ExperienceBucket.MID,
                "effective_year": 2026,
                **overrides,
            }
        )


@pytest.mark.regression
@pytest.mark.parametrize("submissions", [0, 1, 3, 4])
def test_a_suppressed_result_never_reveals_how_many_matched(submissions):
    submit(submissions)

    result = SalaryService.get_insights({"role_title": "Backend Developer"})

    assert result["has_data"] is False
    assert "count" not in result
    assert "sample_size" not in result
    for value in result.values():
        assert str(submissions) not in str(value) or submissions == 0


@pytest.mark.regression
def test_every_suppressed_result_looks_identical():
    """
    Two queries that both fall short must be indistinguishable. A difference
    between them is itself a signal about how many people matched.
    """
    submit(1)
    one = SalaryService.get_insights({"role_title": "Backend Developer"})
    submit(3, salary_lakh=20, role_title="Frontend Developer")
    three = SalaryService.get_insights({"role_title": "Frontend Developer"})
    none = SalaryService.get_insights({"role_title": "Nobody Has This Title"})

    assert one == three == none


@pytest.mark.regression
def test_trimming_below_the_threshold_looks_the_same_as_too_few_rows():
    """
    Five rows where two are junk leaves three. The reply must not differ from
    the reply to three rows, or it reveals that two more existed.
    """
    submit(3)
    for junk in ("1000", "999999999"):
        user_count = SalarySubmission.objects.count()
        from apps.accounts.models import User

        user = User.objects.create_user(email=f"junk{user_count}@test.com", password="TestPass123!")
        SalarySubmission.objects.create(
            user=user,
            role_title="Backend Developer",
            location_city="Bengaluru",
            salary_inr=Decimal(junk),
            company_size_bucket=SalarySubmission.CompanySizeBucket.MEDIUM,
            experience_years_bucket=SalarySubmission.ExperienceBucket.MID,
            effective_year=2026,
        )
    after_trim = SalaryService.get_insights({"role_title": "Backend Developer"})

    submit(3, salary_lakh=30, role_title="Data Engineer")
    plain = SalaryService.get_insights({"role_title": "Data Engineer"})

    assert after_trim == plain


def test_the_threshold_itself_is_still_published():
    """Publishing the rule is fine - it says nothing about who is in the data."""
    submit(2)

    result = SalaryService.get_insights({"role_title": "Backend Developer"})

    assert result["k_threshold"] == 5
    assert "5" in result["message"]


@override_settings(SALARY_K_ANONYMITY=10)
def test_the_message_reflects_a_changed_threshold():
    submit(6)

    result = SalaryService.get_insights({"role_title": "Backend Developer"})

    assert result["k_threshold"] == 10
    assert "10" in result["message"]


def test_reaching_the_threshold_still_reports_the_sample_size():
    """Above K the sample size is safe to publish, and users trust it more."""
    submit(5)

    result = SalaryService.get_insights({"role_title": "Backend Developer"})

    assert result["has_data"] is True
    assert result["sample_size"] == 5
