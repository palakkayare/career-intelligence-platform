"""
Resume plan-gating tests.

Blueprint seeker plan table: "AI Resume Analysis - FREE: No, PRO: Yes".
Upload and file management stay free so one-click apply keeps working on the
free tier; anything that reads parsed output or runs an analysis is gated.
"""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.payments.services import FeatureGateService
from apps.resumes import views as resume_views
from apps.resumes.models import Resume
from apps.resumes.services import ResumeService

pytestmark = pytest.mark.django_db

GATED_VIEWS = [
    "ParsedResumeView",
    "ReparseResumeView",
    "AddResumeSkillView",
    "RemoveResumeSkillView",
    "ConfirmResumeSkillView",
    "AtsScoreView",
    "AdvancedAtsView",
    "ReAnalyzeAdvancedAtsView",
    "ApplicationJdMatchView",
]

FREE_VIEWS = [
    "ResumeListUploadView",
    "ResumeDetailView",
    "SetPrimaryResumeView",
    "DownloadUrlView",
]


def _has_gate(view_name):
    view = getattr(resume_views, view_name)
    return any(cls.__name__ == "HasResumeAiAnalysis" for cls in view.permission_classes)


def _pdf(name="cv.pdf"):
    return SimpleUploadedFile(
        name,
        b"%PDF-1.4 fake resume bytes",
        content_type="application/pdf",
    )


# --------------------------------------------------------------------------
# Plan flags
# --------------------------------------------------------------------------


def test_free_plan_excludes_ai_analysis(free_seeker):
    assert FeatureGateService.get_user_plan(free_seeker.user).slug == "free"
    assert not FeatureGateService.has_feature(free_seeker.user, "resume_ai_analysis")


def test_pro_plan_includes_ai_analysis(seeker):
    assert FeatureGateService.has_feature(seeker.user, "resume_ai_analysis")


# --------------------------------------------------------------------------
# View gating
# --------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("view_name", GATED_VIEWS)
def test_analysis_views_are_plan_gated(view_name):
    """
    Regression: every resume endpoint carried only [IsSeeker], so free users
    got spaCy parsing, ATS scoring and advanced ATS at no charge.
    """
    assert _has_gate(view_name), f"{view_name} must require resume_ai_analysis"


@pytest.mark.parametrize("view_name", FREE_VIEWS)
def test_upload_and_management_views_stay_free(view_name):
    assert not _has_gate(view_name), f"{view_name} must stay on the free tier"


# --------------------------------------------------------------------------
# Parsing is not queued for plans without analysis
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_free_upload_does_not_queue_parsing(free_seeker):
    """Free-tier uploads must not spend spaCy worker time."""
    with patch("apps.resumes.tasks.parse_resume_task.delay") as queued:
        resume = ResumeService.create_resume(
            user=free_seeker.user,
            name="My CV",
            file_obj=_pdf(),
        )

    queued.assert_not_called()
    assert resume.status == Resume.Status.PENDING


def test_pro_upload_queues_parsing(seeker):
    with patch("apps.resumes.tasks.parse_resume_task.delay") as queued:
        resume = ResumeService.create_resume(
            user=seeker.user,
            name="My CV",
            file_obj=_pdf(),
        )

    queued.assert_called_once_with(resume.id)


def test_free_seeker_can_still_upload_and_set_primary(free_seeker):
    with patch("apps.resumes.tasks.parse_resume_task.delay"):
        resume = ResumeService.create_resume(
            user=free_seeker.user,
            name="My CV",
            file_obj=_pdf(),
        )

    resume.refresh_from_db()
    assert resume.is_primary is True, "first resume becomes primary"


def test_free_plan_allows_only_one_resume(free_seeker):
    from rest_framework.exceptions import ValidationError

    with patch("apps.resumes.tasks.parse_resume_task.delay"):
        ResumeService.create_resume(
            user=free_seeker.user,
            name="CV 1",
            file_obj=_pdf("a.pdf"),
        )
        with pytest.raises(ValidationError):
            ResumeService.create_resume(
                user=free_seeker.user,
                name="CV 2",
                file_obj=_pdf("b.pdf"),
            )
