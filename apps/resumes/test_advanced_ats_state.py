"""
What the advanced ATS endpoint says when there is no result yet.

Regression: it answered "still running. Check back in a moment." whenever the
result was missing. That is wrong for a resume that failed to parse, for one
parsed before the feature existed, and for an analysis that gave up - three
cases where waiting never helps and the message never changes.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.resumes.models import Resume
from apps.resumes.views import ADVANCED_ATS_PATIENCE

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(seeker_user):
    api = APIClient()
    api.force_authenticate(user=seeker_user)
    return api


@pytest.fixture
def resume(seeker_user):
    return Resume.objects.create(
        user=seeker_user,
        name="CV",
        original_filename="cv.pdf",
        file="resumes/cv.pdf",
        file_size_bytes=1000,
        status=Resume.Status.PARSED,
        extracted_text="Backend developer with Django and PostgreSQL experience.",
    )


def get_state(client, resume):
    response = client.get(f"/api/v1/resumes/{resume.public_id}/advanced-ats/")
    assert response.status_code == 202
    assert response.data["has_analysis"] is False
    return response.data


@pytest.mark.regression
def test_a_resume_that_was_never_queued_is_not_called_running(client, resume):
    """Tech debt 20: resumes parsed before the feature existed."""
    data = get_state(client, resume)

    assert data["state"] == "never_started"
    assert "running" not in data["message"].lower()
    assert data["can_retry"] is True


@pytest.mark.regression
def test_an_analysis_that_gave_up_is_not_called_running(client, resume):
    resume.advanced_ats_queued_at = timezone.now() - ADVANCED_ATS_PATIENCE - timedelta(minutes=1)
    resume.save(update_fields=["advanced_ats_queued_at"])

    data = get_state(client, resume)

    assert data["state"] == "gave_up"
    assert data["can_retry"] is True


def test_an_analysis_queued_just_now_is_running(client, resume):
    resume.advanced_ats_queued_at = timezone.now()
    resume.save(update_fields=["advanced_ats_queued_at"])

    data = get_state(client, resume)

    assert data["state"] == "running"
    assert data["can_retry"] is False


@pytest.mark.regression
def test_a_resume_still_parsing_says_so(client, resume):
    resume.status = Resume.Status.PARSING
    resume.save(update_fields=["status"])

    data = get_state(client, resume)

    assert data["state"] == "parsing"
    assert data["can_retry"] is False


@pytest.mark.regression
def test_a_resume_that_failed_to_parse_says_so(client, resume):
    resume.status = Resume.Status.FAILED
    resume.save(update_fields=["status"])

    data = get_state(client, resume)

    assert data["state"] == "parse_failed"
    assert "again" in data["message"].lower()
    assert data["can_retry"] is False


def test_a_finished_analysis_is_returned(client, resume):
    resume.advanced_ats_score = 72
    resume.advanced_ats_breakdown = {"advanced_score_pct": 72}
    resume.advanced_ats_analyzed_at = timezone.now()
    resume.save()

    response = client.get(f"/api/v1/resumes/{resume.public_id}/advanced-ats/")

    assert response.status_code == 200
    assert response.data["has_analysis"] is True
    assert response.data["score"] == 72


def test_requesting_an_analysis_marks_it_queued(client, resume):
    response = client.post(f"/api/v1/resumes/{resume.public_id}/re-analyze-ats/")

    assert response.status_code == 202
    resume.refresh_from_db()
    assert resume.advanced_ats_queued_at is not None
    assert get_state(client, resume)["state"] == "running"
