"""
End-to-end tests for GET /api/v1/dashboard/me/ and POST .../seen/.

Fixtures are local to this file (prefixed `dash_`) so the app does not depend
on the shape of the project-wide conftest.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.dashboard.models import SeekerDashboardState
from apps.jobs.models import Job, SavedJob
from apps.match_scores.models import MatchScore
from apps.payments.models import Plan, Subscription
from apps.recruiters.models import CandidateView, Company, RecruiterProfile
from apps.resumes.models import Resume
from apps.seekers.models import SeekerSkill
from apps.skills.models import Skill

pytestmark = pytest.mark.django_db

URL = "/api/v1/dashboard/me/"
SEEN_URL = "/api/v1/dashboard/me/seen/"


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def dash_plans():
    free = Plan.objects.create(name="Free", slug="free", tier="free", max_applications_per_month=5)
    pro = Plan.objects.create(
        name="Pro",
        slug="pro-monthly",
        tier="pro",
        price_inr=499,
        max_applications_per_month=None,
        has_match_score=True,
        has_skill_gap=True,
        has_resume_ai_analysis=True,
    )
    return {"free": free, "pro": pro}


@pytest.fixture
def dash_user_factory(django_user_model):
    def make(email, role="seeker", **extra):
        extra.setdefault("is_email_verified", True)
        return django_user_model.objects.create_user(
            email=email, password="pw-12345678", role=role, **extra
        )

    return make


@pytest.fixture
def dash_seeker(dash_user_factory, dash_plans):
    user = dash_user_factory("palak@example.com", full_name="Palak Kayare")
    profile = user.seeker_profile
    profile.full_name = "Palak Kayare"
    profile.target_role = "Backend Developer"
    profile.save()
    return user


@pytest.fixture
def make_pro(dash_plans):
    def _make(user):
        now = timezone.now()
        return Subscription.objects.create(
            user=user,
            plan=dash_plans["pro"],
            status="active",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
        )

    return _make


@pytest.fixture
def dash_skills():
    return {name: Skill.objects.create(name=name) for name in ("Python", "Django", "Docker", "SQL")}


@pytest.fixture
def dash_recruiter(dash_user_factory):
    user = dash_user_factory("hr@acme.test", role="recruiter")
    company = Company.objects.create(name="Acme Corp", created_by=user)
    profile, _ = RecruiterProfile.objects.get_or_create(user=user, defaults={"company": company})
    if profile.company_id != company.id:
        profile.company = company
        profile.save()
    return profile


@pytest.fixture
def job_factory(dash_recruiter, dash_skills):
    counter = {"n": 0}

    def make(title=None, skills=("Python", "Django"), status=Job.Status.ACTIVE, **extra):
        counter["n"] += 1
        job = Job.objects.create(
            title=title or f"Job {counter['n']}",
            description="A job.",
            company=dash_recruiter.company,
            posted_by=dash_recruiter,
            status=status,
            activated_at=timezone.now() - timedelta(minutes=counter["n"]),
            **extra,
        )
        job.required_skills.set([dash_skills[s] for s in skills])
        return job

    return make


def apply(user, job, status="submitted", **extra):
    return Application.objects.create(seeker=user.seeker_profile, job=job, status=status, **extra)


def add_resume(user, **extra):
    return Resume.objects.create(
        user=user,
        name="CV",
        file="resumes/cv.pdf",
        original_filename="cv.pdf",
        file_size_bytes=1000,
        is_primary=True,
        **extra,
    )


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


# ── access ────────────────────────────────────────────────────────────


def test_url_names_resolve():
    assert reverse("dashboard:seeker-dashboard") == URL
    assert reverse("dashboard:seeker-dashboard-seen") == SEEN_URL


def test_anonymous_is_rejected():
    assert APIClient().get(URL).status_code in (401, 403)


def test_recruiter_is_forbidden(dash_recruiter):
    assert client_for(dash_recruiter.user).get(URL).status_code == 403


# ── free vs pro ───────────────────────────────────────────────────────


def test_free_seeker_gets_latest_jobs_and_a_quota(dash_seeker, job_factory):
    job_factory("Newest")
    applied = job_factory("Already applied")
    apply(dash_seeker, applied)

    body = client_for(dash_seeker).get(URL).json()

    assert body["errors"] == []
    assert body["plan"]["tier"] == "free"
    assert body["top_jobs"]["mode"] == "latest"
    titles = [i["job"]["title"] for i in body["top_jobs"]["items"]]
    assert "Newest" in titles and "Already applied" not in titles
    assert all(i["score"] is None for i in body["top_jobs"]["items"])
    assert body["tiles"]["job_matches"] == {"locked": True, "count": None, "capped": False}
    assert body["tiles"]["quota"] == {"used": 1, "limit": 5, "remaining": 4, "window_days": 30}
    assert body["skill_to_learn"]["locked"] is True


def test_pro_seeker_gets_scored_matches_without_applied_jobs(
    dash_seeker, make_pro, job_factory, dash_skills
):
    make_pro(dash_seeker)
    SeekerSkill.objects.create(seeker=dash_seeker.seeker_profile, skill=dash_skills["Python"])
    strong = job_factory("Strong", skills=("Python", "Docker"))
    taken = job_factory("Taken")
    for job, score in ((strong, 91), (taken, 95)):
        MatchScore.objects.update_or_create(
            seeker=dash_seeker.seeker_profile,
            job=job,
            defaults=dict(
                overall_score=score,
                skills_score=score,
                experience_score=50,
                location_score=50,
                salary_score=50,
            ),
        )
    apply(dash_seeker, taken)
    add_resume(dash_seeker)

    body = client_for(dash_seeker).get(URL).json()

    assert body["top_jobs"]["mode"] == "matches"
    items = body["top_jobs"]["items"]
    assert [i["job"]["title"] for i in items] == ["Strong"]
    assert items[0]["score"] == 91
    assert items[0]["matched_skills"] == ["Python"]
    assert items[0]["missing_skills"] == ["Docker"]
    assert body["tiles"]["quota"] is None
    assert body["tiles"]["job_matches"]["locked"] is False


def test_job_payload_does_not_leak_recruiter_counters(dash_seeker, job_factory):
    job_factory("Visible")
    job = client_for(dash_seeker).get(URL).json()["top_jobs"]["items"][0]["job"]
    assert "application_count" not in job and "rejection_reason" not in job
    assert job["company"]["name"] == "Acme Corp"


# ── sections ──────────────────────────────────────────────────────────


def test_pipeline_counts_live_applications_and_ignores_withdrawn(dash_seeker, job_factory):
    apply(dash_seeker, job_factory(), status="interview")
    apply(dash_seeker, job_factory(), status="submitted")
    withdrawn = apply(dash_seeker, job_factory(), status="withdrawn")
    withdrawn.soft_delete()

    body = client_for(dash_seeker).get(URL).json()

    assert body["pipeline"]["interview"]["count"] == 1
    assert body["pipeline"]["submitted"]["count"] == 1
    assert body["counts"]["total_applications"] == 2
    assert body["counts"]["by_status"]["withdrawn"] == 1
    assert body["tiles"]["interviews"] == 1
    # withdrawn still used a quota slot
    assert body["tiles"]["quota"]["used"] == 3


def test_new_account_is_flagged_and_asked_for_a_resume(dash_user_factory, dash_plans):
    user = dash_user_factory("new@example.com")
    body = client_for(user).get(URL).json()
    assert body["counts"]["is_new_user"] is True
    assert body["next_action"]["id"] == "resume"
    assert body["health"]["resume"]["has_resume"] is False


def test_health_shows_the_basic_ats_score_and_adds_ai_score_for_pro(dash_seeker, make_pro):
    """
    The headline score matches the "analysis ready" email (basic ATS). The AI
    score is a separate number, shown only to Pro.
    """
    add_resume(
        dash_seeker, ats_score=94, advanced_ats_score=54, advanced_ats_analyzed_at=timezone.now()
    )

    free = client_for(dash_seeker).get(URL).json()["health"]["resume"]
    assert (free["ats_score"], free["ai_score"]) == (94, None)

    make_pro(dash_seeker)
    cache.clear()
    pro = client_for(dash_seeker).get(URL).json()["health"]["resume"]
    assert (pro["ats_score"], pro["ai_score"]) == (94, 54)


def test_resume_without_a_score_is_pending(dash_seeker):
    add_resume(dash_seeker)
    resume = client_for(dash_seeker).get(URL).json()["health"]["resume"]
    assert resume["ats_score"] is None and resume["ats_pending"] is True


def test_offer_is_the_next_action_and_first_attention_item(dash_seeker, job_factory):
    add_resume(dash_seeker)
    app = apply(dash_seeker, job_factory("Dream job"), status="offered")

    body = client_for(dash_seeker).get(URL).json()

    assert body["next_action"]["id"] == "offer"
    assert body["attention"][0]["id"] == f"offer-{app.id}"


def test_saved_job_closing_soon_is_flagged(dash_seeker, job_factory):
    soon = job_factory("Closing", application_deadline=timezone.now() + timedelta(hours=20))
    later = job_factory("Later", application_deadline=timezone.now() + timedelta(days=10))
    SavedJob.objects.create(user=dash_seeker, job=soon)
    SavedJob.objects.create(user=dash_seeker, job=later)

    items = client_for(dash_seeker).get(URL).json()["attention"]

    assert [i["kind"] for i in items] == ["deadline"]
    assert items[0]["text"] == "Closing closes within a day"


# ── last seen ─────────────────────────────────────────────────────────


def test_get_never_moves_last_seen(dash_seeker):
    client_for(dash_seeker).get(URL)
    assert not SeekerDashboardState.objects.filter(seeker=dash_seeker.seeker_profile).exists()


def test_seen_records_the_visit(dash_seeker):
    response = client_for(dash_seeker).post(SEEN_URL)
    assert response.status_code == 200
    assert "last_seen_at" in response.json()
    state = SeekerDashboardState.objects.get(seeker=dash_seeker.seeker_profile)
    assert timezone.now() - state.last_seen_at < timedelta(seconds=5)


def test_changes_after_last_visit_appear(dash_seeker, job_factory, dash_recruiter):
    add_resume(dash_seeker)
    app = apply(dash_seeker, job_factory("Watched"))
    SeekerDashboardState.objects.create(
        seeker=dash_seeker.seeker_profile, last_seen_at=timezone.now() - timedelta(days=1)
    )
    Application.objects.filter(pk=app.pk).update(
        status="shortlisted", last_status_change_at=timezone.now()
    )
    CandidateView.objects.create(
        recruiter=dash_recruiter, seeker=dash_seeker.seeker_profile, view_kind="detail"
    )
    CandidateView.objects.create(
        recruiter=dash_recruiter, seeker=dash_seeker.seeker_profile, view_kind="search_result"
    )

    kinds = [i["kind"] for i in client_for(dash_seeker).get(URL).json()["attention"]]

    assert kinds == ["status_change", "profile_views"]


# ── robustness ────────────────────────────────────────────────────────


def test_a_failing_section_does_not_break_the_page(dash_seeker):
    with patch("apps.dashboard.services.section_pipeline", side_effect=RuntimeError("boom")):
        from apps.dashboard import services

        sections = tuple(
            (name, services.section_pipeline if name == "pipeline" else fn)
            for name, fn in services.SECTIONS
        )
        with patch.object(services, "SECTIONS", sections):
            response = client_for(dash_seeker).get(URL)

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline"] is None
    assert body["errors"] == ["pipeline"]
    assert body["tiles"] is not None
    # a broken response is not cached
    assert cache.get(f"dashboard:seeker:{dash_seeker.pk}") is None


def test_response_is_cached_and_invalidated_by_a_new_application(dash_seeker, job_factory):
    client = client_for(dash_seeker)
    first = client.get(URL).json()
    assert first["counts"]["total_applications"] == 0

    apply(dash_seeker, job_factory())
    second = client.get(URL).json()
    assert second["counts"]["total_applications"] == 1


def test_query_count_does_not_grow_with_applications(dash_seeker, make_pro, job_factory):
    make_pro(dash_seeker)
    add_resume(dash_seeker)
    client = client_for(dash_seeker)

    apply(dash_seeker, job_factory())
    cache.clear()
    with CaptureQueriesContext(connection) as few:
        assert client.get(URL).status_code == 200

    for _ in range(25):
        apply(dash_seeker, job_factory())
    cache.clear()
    with CaptureQueriesContext(connection) as many:
        assert client.get(URL).status_code == 200

    assert len(many) == len(few), [q["sql"][:120] for q in many.captured_queries]
    assert len(few) <= 20


def test_response_matches_the_documented_shape(dash_seeker, make_pro, job_factory):
    """The schema serializer is documentation; keep it honest."""
    from apps.dashboard.serializers import DashboardResponseSerializer

    make_pro(dash_seeker)
    add_resume(dash_seeker, ats_score=50)
    apply(dash_seeker, job_factory(), status="interview")
    body = client_for(dash_seeker).get(URL).json()

    documented = set(DashboardResponseSerializer().fields)
    assert set(body) == documented
    assert set(body["tiles"]) == set(DashboardResponseSerializer().fields["tiles"].fields)
    assert set(body["health"]) == set(DashboardResponseSerializer().fields["health"].fields)
    assert set(body["health"]["resume"]) == set(
        DashboardResponseSerializer().fields["health"].fields["resume"].fields
    )
    assert set(body["next_action"]) == set(
        DashboardResponseSerializer().fields["next_action"].fields
    )
    assert set(body["skill_to_learn"]) == set(
        DashboardResponseSerializer().fields["skill_to_learn"].fields
    )
