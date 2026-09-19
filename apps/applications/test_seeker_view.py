"""
What a candidate can read about their own application.

Regression: the candidate's timeline returned the recruiter's email and the
note typed with each status change, and the embedded job carried the
recruiter's counters.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.applications.services import ApplicationStatusService
from apps.jobs.models import Job
from apps.payments.models import Plan, Subscription
from apps.recruiters.models import Company, RecruiterProfile
from apps.resumes.models import Resume

pytestmark = pytest.mark.django_db


@pytest.fixture
def recruiter(django_user_model):
    user = django_user_model.objects.create_user(
        email="private.recruiter@acme.test", password="pw-12345678", role="recruiter"
    )
    company = Company.objects.create(name="Acme", created_by=user)
    profile, _ = RecruiterProfile.objects.get_or_create(user=user)
    profile.company = company
    profile.save()
    return profile


@pytest.fixture
def seeker(django_user_model):
    return django_user_model.objects.create_user(
        email="candidate@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )


@pytest.fixture
def application(recruiter, seeker):
    job = Job.objects.create(
        title="Backend",
        description="Role",
        company=recruiter.company,
        posted_by=recruiter,
        status=Job.Status.ACTIVE,
        activated_at=timezone.now(),
        view_count=99,
        application_count=12,
    )
    app = Application.objects.create(seeker=seeker.seeker_profile, job=job)
    from apps.applications.models import ApplicationStatusHistory

    ApplicationStatusHistory.objects.create(
        application=app,
        from_status="",
        to_status="submitted",
        changed_by=seeker,
        notes="Initial application",
    )
    ApplicationStatusService.update_status(
        app,
        new_status="reviewing",
        actor=recruiter.user,
        notes="Weak communication, keep as backup",
    )
    return app


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_candidate_timeline_hides_the_recruiter(seeker, application):
    rows = client_for(seeker).get(f"/api/v1/applications/me/{application.id}/history/").json()

    assert [r["to_status"] for r in rows] == ["submitted", "reviewing"]
    assert [r["actor"] for r in rows] == ["you", "employer"]
    body = str(rows)
    assert "private.recruiter@acme.test" not in body
    assert "Weak communication" not in body
    assert "changed_by_email" not in rows[0]


def test_candidate_keeps_their_own_notes(seeker, application):
    client_for(seeker).post(f"/api/v1/applications/me/{application.id}/withdraw/")
    rows = client_for(seeker).get(f"/api/v1/applications/me/{application.id}/history/").json()

    assert rows[-1]["to_status"] == "withdrawn"
    assert rows[-1]["actor"] == "you"
    assert rows[-1]["notes"] == "Withdrawn by candidate."


def test_recruiter_timeline_is_unchanged(recruiter, application):
    rows = client_for(recruiter.user).get(f"/api/v1/applications/{application.id}/history/").json()

    assert rows[-1]["changed_by_email"] == "private.recruiter@acme.test"
    assert rows[-1]["notes"] == "Weak communication, keep as backup"


def test_another_seeker_cannot_read_the_timeline(django_user_model, application):
    other = django_user_model.objects.create_user(
        email="nosy@example.com", password="pw-12345678", role="seeker"
    )
    response = client_for(other).get(f"/api/v1/applications/me/{application.id}/history/")
    assert response.status_code == 403


def test_candidate_application_does_not_carry_recruiter_counters(seeker, application):
    body = client_for(seeker).get(f"/api/v1/applications/me/{application.id}/").json()
    for field in ("view_count", "application_count", "rejection_reason"):
        assert field not in body["job"]
    assert body["job"]["title"] == "Backend"

    rows = client_for(seeker).get("/api/v1/applications/me/").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert "application_count" not in rows[0]["job"]


# ── JD match uses the resume that was sent ────────────────────────────


@pytest.fixture
def pro(seeker):
    plan = Plan.objects.create(
        name="Pro", slug="pro-jd", tier="pro", price_inr=499, has_resume_ai_analysis=True
    )
    now = timezone.now()
    Subscription.objects.create(
        user=seeker,
        plan=plan,
        status="active",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    return seeker


def _resume(user, name, **extra):
    return Resume.objects.create(
        user=user,
        name=name,
        file="resumes/x.pdf",
        original_filename="x.pdf",
        file_size_bytes=10,
        status="parsed",
        extracted_text=f"{name} resume text with Python and Django experience " * 5,
        **extra,
    )


def _jd_match(user, app):
    with patch("apps.resumes.ats_advanced.run_full_analysis", return_value={"ok": True}) as run:
        response = client_for(user).get(f"/api/v1/applications/{app.id}/jd-match/")
    return response, run


def test_jd_match_scores_the_resume_that_was_sent(pro, application):
    _resume(pro, "Primary", is_primary=True)
    sent = _resume(pro, "Sent")
    Application.objects.filter(pk=application.pk).update(resume=sent)

    response, run = _jd_match(pro, application)

    assert response.status_code == 200, response.content
    assert response.json()["resume"]["name"] == "Sent"
    assert response.json()["resume"]["is_the_one_sent"] is True
    assert run.call_args.kwargs["resume_text"].startswith("Sent resume")


def test_jd_match_falls_back_when_the_sent_resume_is_gone(pro, application):
    _resume(pro, "Primary", is_primary=True)
    sent = _resume(pro, "Deleted")
    Application.objects.filter(pk=application.pk).update(resume=sent)
    Resume.objects.filter(pk=sent.pk).update(is_deleted=True)

    response, _ = _jd_match(pro, application)

    assert response.json()["resume"] == {
        "public_id": str(Resume.objects.get(name="Primary").public_id),
        "name": "Primary",
        "is_the_one_sent": False,
    }
