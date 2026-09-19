"""GET /api/v1/dashboard/recruiter/"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.jobs.models import Job
from apps.match_scores.models import MatchScore
from apps.payments.models import Plan, Subscription
from apps.recruiters.models import Company, RecruiterProfile

pytestmark = pytest.mark.django_db
URL = "/api/v1/dashboard/recruiter/"


def make_recruiter(django_user_model, email, company_name, full_name="Asha Rao"):
    user = django_user_model.objects.create_user(
        email=email, password="pw-12345678", role="recruiter"
    )
    company = Company.objects.create(name=company_name, created_by=user)
    profile, _ = RecruiterProfile.objects.get_or_create(user=user)
    profile.company = company
    profile.full_name = full_name
    profile.save()
    return profile


@pytest.fixture
def plans():
    free = Plan.objects.create(name="Free", slug="free", tier="free", max_applicants_view_per_job=2)
    business = Plan.objects.create(
        name="Business",
        slug="business-x",
        tier="business",
        price_inr=2999,
        max_applicants_view_per_job=None,
        has_candidate_search=True,
    )
    return free, business


@pytest.fixture
def recruiter(django_user_model, plans):
    return make_recruiter(django_user_model, "owner@hire.test", "Hire Co")


def job(recruiter, title, status=Job.Status.ACTIVE):
    return Job.objects.create(
        title=title,
        description="Role",
        company=recruiter.company,
        posted_by=recruiter,
        status=status,
        activated_at=timezone.now(),
    )


def seeker(django_user_model, n):
    user = django_user_model.objects.create_user(
        email=f"cand{n}@example.com", password="pw-12345678", role="seeker"
    )
    user.seeker_profile.full_name = f"Candidate {n}"
    user.seeker_profile.save()
    return user.seeker_profile


def apply(profile, j, status="submitted", days_ago=0):
    a = Application.objects.create(seeker=profile, job=j, status=status)
    when = timezone.now() - timedelta(days=days_ago)
    Application.objects.filter(pk=a.pk).update(submitted_at=when, last_status_change_at=when)
    return a


def get(user):
    c = APIClient()
    c.force_authenticate(user)
    r = c.get(URL)
    assert r.status_code == 200, r.content
    return r.json()


def test_counts_every_applicant_not_just_a_first_page(django_user_model, recruiter):
    j = job(recruiter, "Backend")
    for n in range(25):
        apply(seeker(django_user_model, n), j, status="shortlisted" if n < 3 else "submitted")

    body = get(recruiter.user)

    assert body["tiles"]["applicants_total"] == 25
    assert body["tiles"]["in_progress"] == 3
    assert body["pipeline"]["submitted"] == 22
    assert body["jobs_needing_review"] == [
        {"public_id": str(j.public_id), "title": "Backend", "new_count": 22, "total": 25}
    ]


def test_greets_the_person_and_names_the_company(recruiter):
    body = get(recruiter.user)
    assert body["recruiter_name"] == "Asha Rao"
    assert body["company_name"] == "Hire Co"


def test_only_counts_the_recruiters_own_jobs(django_user_model, recruiter):
    rival = make_recruiter(django_user_model, "rival@hire.test", "Rival Co")
    apply(seeker(django_user_model, 1), job(rival, "Theirs"))
    apply(seeker(django_user_model, 2), job(recruiter, "Mine"))

    body = get(recruiter.user)

    assert body["tiles"]["applicants_total"] == 1
    assert [r["job_title"] for r in body["recent_applicants"]] == ["Mine"]


def test_thirty_day_change_and_week_buckets(django_user_model, recruiter):
    j = job(recruiter, "Backend")
    apply(seeker(django_user_model, 1), j, days_ago=0)
    apply(seeker(django_user_model, 2), j, days_ago=2)
    apply(seeker(django_user_model, 3), j, days_ago=40)

    body = get(recruiter.user)

    assert body["tiles"]["applicants_30d"] == 2
    assert body["tiles"]["applicants_change_pct"] == 100
    assert len(body["week"]) == 7
    assert sum(d["count"] for d in body["week"]) == 2
    assert body["week"][-1]["count"] == 1


def test_free_plan_names_only_applicants_inside_the_view_cap(django_user_model, recruiter):
    j = job(recruiter, "Backend")
    for n in range(5):
        apply(seeker(django_user_model, n), j, days_ago=n)

    body = get(recruiter.user)

    names = [r["candidate_name"] for r in body["recent_applicants"]]
    assert names == ["Candidate 0", "Candidate 1"]  # newest two, the cap
    assert body["applicants_view_limit"] == 2
    assert body["tiles"]["applicants_total"] == 5  # counts are not gated


def test_match_scores_only_with_candidate_search(django_user_model, recruiter, plans):
    _, business = plans
    j = job(recruiter, "Backend")
    s = seeker(django_user_model, 1)
    apply(s, j)
    MatchScore.objects.update_or_create(
        seeker=s,
        job=j,
        defaults=dict(
            overall_score=81.6,
            skills_score=80,
            experience_score=80,
            location_score=80,
            salary_score=80,
        ),
    )

    assert get(recruiter.user)["recent_applicants"][0]["match_score"] is None

    now = timezone.now()
    Subscription.objects.create(
        user=recruiter.user,
        plan=business,
        status="active",
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=20),
    )
    body = get(recruiter.user)
    assert body["can_see_match_scores"] is True
    assert body["recent_applicants"][0]["match_score"] == 82


def test_seekers_are_refused(django_user_model):
    user = django_user_model.objects.create_user(
        email="nope@example.com", password="pw-12345678", role="seeker"
    )
    c = APIClient()
    c.force_authenticate(user)
    assert c.get(URL).status_code == 403
