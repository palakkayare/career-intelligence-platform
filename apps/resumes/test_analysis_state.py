"""
`analysis_state` tells a stuck or skipped parse apart from a queued one.

Regression: every resume a Free seeker uploaded stayed "pending" forever,
because parsing is plan-gated and never queued - and the page could not
tell that from a parse that was merely slow.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.payments.models import Plan, Subscription
from apps.resumes.analysis_state import analysis_state, can_reanalyse
from apps.resumes.models import Resume

NOW = timezone.now()


def fake(status, minutes_ago=0):
    t = NOW - timedelta(minutes=minutes_ago)
    return SimpleNamespace(status=status, updated_at=t, created_at=t)


# ── pure ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status, minutes, has, expected",
    [
        ("parsed", 0, True, "ready"),
        ("parsed", 0, False, "ready"),
        ("failed", 0, True, "failed"),
        ("pending", 0, True, "queued"),
        ("pending", 5, True, "stuck"),
        ("parsing", 3, True, "analysing"),
        ("parsing", 30, True, "stuck"),
        ("pending", 0, False, "not_included"),
        ("pending", 500, False, "not_included"),
        ("parsing", 1, False, "analysing"),
    ],
)
def test_states(status, minutes, has, expected):
    assert analysis_state(fake(status, minutes), has_analysis=has, now=NOW) == expected


def test_retry_is_offered_only_when_it_can_help():
    assert can_reanalyse("stuck", has_analysis=True)
    assert can_reanalyse("failed", has_analysis=True)
    assert not can_reanalyse("queued", has_analysis=True)
    assert not can_reanalyse("ready", has_analysis=True)
    assert not can_reanalyse("failed", has_analysis=False)


# ── through the API ───────────────────────────────────────────────────


@pytest.fixture
def plans(db):
    free = Plan.objects.create(name="Free", slug="free", tier="free", max_resumes=1)
    pro = Plan.objects.create(
        name="Pro",
        slug="pro-x",
        tier="pro",
        price_inr=499,
        max_resumes=5,
        has_resume_ai_analysis=True,
    )
    return free, pro


@pytest.fixture
def seeker(db, django_user_model, plans):
    return django_user_model.objects.create_user(
        email="cv-owner@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _resume(user, **extra):
    extra.setdefault("status", "pending")
    return Resume.objects.create(
        user=user,
        name="CV",
        file="resumes/cv.pdf",
        original_filename="cv.pdf",
        file_size_bytes=10,
        is_primary=True,
        **extra,
    )


@pytest.mark.django_db
def test_free_upload_is_reported_as_not_included(seeker, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    response = _client(seeker).post(
        "/api/v1/resumes/",
        {
            "name": "Mine",
            "file": SimpleUploadedFile("cv.pdf", b"%PDF-1.4 x", content_type="application/pdf"),
        },
        format="multipart",
    )
    assert response.status_code == 202, response.content
    body = response.json()
    assert body["status"] == "pending"
    assert body["analysis_state"] == "not_included"
    assert body["can_reanalyse"] is False

    listed = _client(seeker).get("/api/v1/resumes/").json()
    rows = listed["results"] if isinstance(listed, dict) else listed
    assert rows[0]["analysis_state"] == "not_included"


@pytest.mark.django_db
def test_pro_resume_waiting_too_long_is_stuck_and_retryable(seeker, plans):
    _, pro = plans
    now = timezone.now()
    Subscription.objects.create(
        user=seeker,
        plan=pro,
        status="active",
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=20),
    )
    resume = _resume(seeker)
    Resume.objects.filter(pk=resume.pk).update(updated_at=now - timedelta(minutes=30))

    body = _client(seeker).get(f"/api/v1/resumes/{resume.public_id}/").json()

    assert body["analysis_state"] == "stuck"
    assert body["can_reanalyse"] is True


@pytest.mark.django_db
def test_reparse_restarts_the_clock(seeker, plans):
    _, pro = plans
    now = timezone.now()
    Subscription.objects.create(
        user=seeker,
        plan=pro,
        status="active",
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=20),
    )
    resume = _resume(seeker, status="failed")
    Resume.objects.filter(pk=resume.pk).update(updated_at=now - timedelta(hours=2))

    from unittest.mock import patch

    with patch("apps.resumes.tasks.parse_resume_task.delay"):
        assert (
            _client(seeker).post(f"/api/v1/resumes/{resume.public_id}/reparse/").status_code == 202
        )

    resume.refresh_from_db()
    assert timezone.now() - resume.updated_at < timedelta(seconds=10)
    body = _client(seeker).get(f"/api/v1/resumes/{resume.public_id}/").json()
    assert body["analysis_state"] == "queued"


@pytest.mark.django_db
def test_list_looks_up_the_plan_once(seeker, django_assert_max_num_queries):
    for i in range(4):
        Resume.objects.create(
            user=seeker,
            name=f"CV {i}",
            file="resumes/cv.pdf",
            original_filename="cv.pdf",
            file_size_bytes=10,
        )
    client = _client(seeker)
    with django_assert_max_num_queries(8) as ctx:
        assert client.get("/api/v1/resumes/").status_code == 200
    few = len(ctx.captured_queries)

    for i in range(4, 12):
        Resume.objects.create(
            user=seeker,
            name=f"CV {i}",
            file="resumes/cv.pdf",
            original_filename="cv.pdf",
            file_size_bytes=10,
        )
    with django_assert_max_num_queries(few):
        assert client.get("/api/v1/resumes/").status_code == 200
