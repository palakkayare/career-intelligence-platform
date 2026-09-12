"""
The backfill command for resumes that never had an advanced ATS analysis.
"""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.resumes.models import Resume
from apps.resumes.views import ADVANCED_ATS_PATIENCE

pytestmark = pytest.mark.django_db


def make_resume(seeker_user, **overrides):
    return Resume.objects.create(
        **{
            "user": seeker_user,
            "name": "CV",
            "original_filename": "cv.pdf",
            "file": "resumes/cv.pdf",
            "file_size_bytes": 1000,
            "status": Resume.Status.PARSED,
            "extracted_text": "Backend developer.",
            **overrides,
        }
    )


def run(**options):
    out = StringIO()
    call_command("queue_missing_advanced_ats", stdout=out, **options)
    return out.getvalue()


def test_a_resume_without_an_analysis_is_queued(seeker_user):
    resume = make_resume(seeker_user)

    output = run()

    resume.refresh_from_db()
    assert resume.advanced_ats_queued_at is not None
    assert "Queued 1" in output


def test_a_resume_with_a_result_is_left_alone(seeker_user):
    make_resume(seeker_user, advanced_ats_analyzed_at=timezone.now(), advanced_ats_score=70)

    assert "Queued 0" in run()


def test_a_resume_queued_moments_ago_is_not_queued_again(seeker_user):
    make_resume(seeker_user, advanced_ats_queued_at=timezone.now())

    assert "Queued 0" in run()


def test_a_resume_queued_long_ago_is_retried(seeker_user):
    """It gave up; leaving it alone would mean it is never analysed."""
    make_resume(
        seeker_user,
        advanced_ats_queued_at=timezone.now() - ADVANCED_ATS_PATIENCE - timedelta(minutes=1),
    )

    assert "Queued 1" in run()


def test_an_unparsed_resume_is_skipped(seeker_user):
    make_resume(seeker_user, status=Resume.Status.PARSING)

    assert "Queued 0" in run()


def test_a_deleted_resume_is_skipped(seeker_user):
    make_resume(seeker_user, is_deleted=True)

    assert "Queued 0" in run()


def test_dry_run_changes_nothing(seeker_user):
    resume = make_resume(seeker_user)

    output = run(dry_run=True)

    resume.refresh_from_db()
    assert resume.advanced_ats_queued_at is None
    assert "Would queue 1" in output


def test_limit_queues_a_batch_and_reports_the_total(seeker_user):
    for _ in range(3):
        make_resume(seeker_user)

    output = run(limit=2)

    assert "Queued 2 of 3" in output
    assert Resume.objects.filter(advanced_ats_queued_at__isnull=False).count() == 2
