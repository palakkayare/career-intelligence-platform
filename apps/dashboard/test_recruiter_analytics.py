"""
GET /api/v1/dashboard/recruiter/analytics/

The page used to build these numbers in the browser from one request per
job, each capped at 20 applicants, so a busy job under-reported.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.dashboard.test_recruiter import apply, job, make_recruiter, seeker
from apps.payments.models import Plan, Subscription
from apps.skills.models import Skill

pytestmark = pytest.mark.django_db
URL = "/api/v1/dashboard/recruiter/analytics/"


@pytest.fixture
def business_plan():
    return Plan.objects.create(
        name="Business",
        slug="business-an",
        tier="business",
        price_inr=2999,
        has_analytics_dashboard=True,
        max_applicants_view_per_job=None,
    )


@pytest.fixture
def recruiter(django_user_model, business_plan):
    profile = make_recruiter(django_user_model, "analytics@hire.test", "Analytics Co")
    now = timezone.now()
    Subscription.objects.create(
        user=profile.user,
        plan=business_plan,
        status="active",
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=20),
    )
    return profile


def get(user):
    c = APIClient()
    c.force_authenticate(user)
    r = c.get(URL)
    assert r.status_code == 200, r.content
    return r.json()


def test_counts_past_the_twenty_row_page(django_user_model, recruiter):
    busy = job(recruiter, "Backend")
    for n in range(25):
        apply(seeker(django_user_model, n), busy, status="offered" if n < 2 else "submitted")

    body = get(recruiter.user)

    assert body["totals"]["applicants"] == 25
    assert body["totals"]["offers"] == 2
    assert body["per_job"][0] == {
        "public_id": str(busy.public_id),
        "title": "Backend",
        "status": "active",
        "applicants": 25,
        "in_pipeline": 2,
        "offered": 2,
        "accepted": 0,
    }
    assert body["funnel"]["submitted"] == 23


def offered_on(application, days_ago):
    """Record the moment the offer was made, as the status service would."""
    from apps.applications.models import ApplicationStatusHistory

    row = ApplicationStatusHistory.objects.create(
        application=application, from_status="interview", to_status="offered"
    )
    ApplicationStatusHistory.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago)
    )


def test_rates_and_average_time_to_offer(django_user_model, recruiter):
    j = job(recruiter, "Backend")
    a1 = apply(seeker(django_user_model, 1), j, status="offered", days_ago=10)
    offered_on(a1, 0)
    Application.objects.filter(pk=a1.pk).update(last_status_change_at=timezone.now())
    apply(seeker(django_user_model, 2), j, status="interview")
    apply(seeker(django_user_model, 3), j, status="submitted")
    apply(seeker(django_user_model, 4), j, status="submitted")

    body = get(recruiter.user)

    assert body["rates"]["review_pct"] == 50  # two of four moved past "applied"
    assert body["rates"]["interview_pct"] == 50
    assert body["rates"]["offer_pct"] == 25
    assert body["rates"]["applicants_per_job"] == 4.0
    assert body["totals"]["avg_days_to_offer"] == 10


def test_months_cover_the_last_eight_including_now(django_user_model, recruiter):
    j = job(recruiter, "Backend")
    apply(seeker(django_user_model, 1), j, days_ago=0)

    body = get(recruiter.user)

    assert len(body["months"]) == 8
    assert body["months"][-1]["count"] == 1
    assert body["months"][0]["count"] == 0


def test_top_skills_are_weighted_by_applicants(django_user_model, recruiter):
    django, docker = Skill.objects.create(name="Django"), Skill.objects.create(name="Docker")
    busy = job(recruiter, "Backend")
    busy.required_skills.add(django)
    quiet = job(recruiter, "Ops")
    quiet.required_skills.add(docker)
    for n in range(5):
        apply(seeker(django_user_model, n), busy)

    skills = get(recruiter.user)["top_skills"]

    assert [s["name"] for s in skills] == ["Django", "Docker"]
    assert skills[0]["share_pct"] > skills[1]["share_pct"]


def test_a_plan_without_analytics_is_refused(django_user_model):
    profile = make_recruiter(django_user_model, "free-an@hire.test", "Free Co")
    c = APIClient()
    c.force_authenticate(profile.user)
    assert c.get(URL).status_code == 403


def test_only_my_own_jobs_count(django_user_model, recruiter):
    rival = make_recruiter(django_user_model, "rival-an@hire.test", "Rival Co")
    apply(seeker(django_user_model, 1), job(rival, "Theirs"))
    apply(seeker(django_user_model, 2), job(recruiter, "Mine"))

    body = get(recruiter.user)

    assert body["totals"]["applicants"] == 1
    assert [row["title"] for row in body["per_job"]] == ["Mine"]


def test_offers_count_however_the_candidate_answered(django_user_model, recruiter):
    """An offer that was declined was still an offer the company made."""
    j = job(recruiter, "Backend")
    apply(seeker(django_user_model, 1), j, status="offered")
    apply(seeker(django_user_model, 2), j, status="offer_accepted")
    apply(seeker(django_user_model, 3), j, status="offer_declined")

    body = get(recruiter.user)

    assert body["totals"]["offers"] == 3
    assert body["totals"]["offers_accepted"] == 1
    assert body["totals"]["offers_declined"] == 1
    assert body["rates"]["accept_pct"] == 33
    assert body["per_job"][0]["offered"] == 3
    assert body["per_job"][0]["accepted"] == 1


def test_time_to_offer_stops_at_the_offer(django_user_model, recruiter):
    """
    Regression: the average ran to the application's last status change, so a
    candidate answering two weeks later made the offer look two weeks slower.
    """
    j = job(recruiter, "Backend")
    accepted = apply(seeker(django_user_model, 1), j, status="offer_accepted", days_ago=30)
    offered_on(accepted, 25)  # offered five days after applying
    Application.objects.filter(pk=accepted.pk).update(last_status_change_at=timezone.now())

    assert get(recruiter.user)["totals"]["avg_days_to_offer"] == 5


def test_the_skills_chart_names_the_skills(django_user_model, recruiter):
    """
    Regression: the chart showed five skills and swept the rest into
    "Others", which took two thirds of the donut on a normal set of jobs -
    a chart whose biggest slice is "everything else" answers nothing.
    """
    from apps.skills.models import Skill

    for n in range(14):
        j = job(recruiter, f"Role {n}")
        j.required_skills.add(Skill.objects.create(name=f"Skill {n}"))
        apply(seeker(django_user_model, n), j)

    skills = get(recruiter.user)["top_skills"]

    named = [s for s in skills if s["name"] != "Others"]
    others = next((s for s in skills if s["name"] == "Others"), None)

    assert len(named) == 10
    # Either there is no "Others" at all, or it is a small remainder.
    assert others is None or others["share_pct"] <= 10
