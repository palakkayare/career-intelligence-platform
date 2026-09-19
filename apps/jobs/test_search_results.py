"""
What a search result row carries.

- A Pro seeker sees their own match score on every result, whatever the sort.
- Everyone else gets `match_score: null` and no match ordering.
- The public search never exposes recruiter-side counters.
- The experience filter is `experience` (years the seeker has).
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jobs.models import Job
from apps.match_scores.models import MatchScore
from apps.payments.models import Plan, Subscription
from apps.recruiters.models import Company, RecruiterProfile

pytestmark = pytest.mark.django_db

URL = "/api/v1/jobs/search/"


@pytest.fixture
def plans():
    Plan.objects.create(name="Free", slug="free", tier="free")
    return Plan.objects.create(
        name="Pro", slug="pro-s", tier="pro", price_inr=499, has_match_score=True
    )


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@acme.test", password="pw-12345678", role="recruiter", is_email_verified=True
    )
    company = Company.objects.create(name="Search Co", created_by=user)
    profile, _ = RecruiterProfile.objects.get_or_create(user=user, defaults={"company": company})
    return profile


@pytest.fixture
def make_job(owner):
    def make(title, minutes_ago=0, **extra):
        return Job.objects.create(
            title=title,
            description="Role",
            company=owner.company or Company.objects.first(),
            posted_by=owner,
            status=Job.Status.ACTIVE,
            activated_at=timezone.now() - timedelta(minutes=minutes_ago),
            **extra,
        )

    return make


def seeker(django_user_model, email, pro_plan=None):
    user = django_user_model.objects.create_user(
        email=email, password="pw-12345678", role="seeker", is_email_verified=True
    )
    if pro_plan:
        now = timezone.now()
        Subscription.objects.create(
            user=user,
            plan=pro_plan,
            status="active",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=20),
        )
    return user


def score(user, job, value):
    MatchScore.objects.update_or_create(
        seeker=user.seeker_profile,
        job=job,
        defaults=dict(
            overall_score=value,
            skills_score=value,
            experience_score=50,
            location_score=50,
            salary_score=50,
        ),
    )


def rows(client, query=""):
    return client.get(URL + query).json()["results"]


def as_user(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_pro_seeker_sees_their_score_on_every_row(django_user_model, plans, make_job):
    pro = seeker(django_user_model, "pro@example.com", plans)
    strong = make_job("Strong", minutes_ago=10)
    make_job("Unscored", minutes_ago=1)
    score(pro, strong, 91.26)

    by_date = {r["title"]: r["match_score"] for r in rows(as_user(pro), "?sort=date")}

    assert by_date == {"Strong": 91.3, "Unscored": None}


def test_pro_seeker_can_sort_by_match(django_user_model, plans, make_job):
    pro = seeker(django_user_model, "pro2@example.com", plans)
    low = make_job("Low", minutes_ago=0)
    high = make_job("High", minutes_ago=30)
    score(pro, low, 40)
    score(pro, high, 90)

    titles = [r["title"] for r in rows(as_user(pro), "?sort=match_score")]

    assert titles == ["High", "Low"]


def test_free_seeker_gets_no_scores_and_no_match_order(django_user_model, plans, make_job):
    free = seeker(django_user_model, "free@example.com")
    low = make_job("Newer", minutes_ago=0)
    high = make_job("Older", minutes_ago=30)
    score(free, low, 10)
    score(free, high, 99)

    results = rows(as_user(free), "?sort=match_score")

    assert [r["title"] for r in results] == ["Newer", "Older"]
    assert all(r["match_score"] is None for r in results)


def test_anonymous_search_has_no_scores(plans, make_job):
    make_job("Open")
    results = rows(APIClient())
    assert results[0]["match_score"] is None


def test_search_rows_hide_recruiter_counters(plans, make_job):
    make_job("Open")
    row = rows(APIClient())[0]
    for field in ("application_count", "view_count", "rejection_reason"):
        assert field not in row
    assert row["title"] == "Open"


def test_experience_filter_keeps_jobs_the_seeker_qualifies_for(plans, make_job):
    make_job("Entry", min_experience_years=0)
    make_job("Mid", min_experience_years=3)
    make_job("Senior", min_experience_years=6)

    titles = {r["title"] for r in rows(APIClient(), "?experience=3")}

    assert titles == {"Entry", "Mid"}
