from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.permissions import HasFeature
from apps.seekers.permissions import IsSeeker

from .models import Resume, ResumeSkill
from .serializers import (
    AddSkillSerializer,
    ResumeDetailSerializer,
    ResumeListSerializer,
    ResumeParsedSerializer,
    ResumeSkillSerializer,
    ResumeUploadSerializer,
)
from .services import ResumeService

# Blueprint seeker plan table: "AI Resume Analysis — FREE: No, PRO: Yes".
# Upload and file management stay free so that one-click apply keeps working
# on the free tier; everything that reads parsed output or runs an analysis
# is gated behind the plan flag.
HasResumeAiAnalysis = HasFeature.create("resume_ai_analysis")


class ResumeListUploadView(generics.ListCreateAPIView):
    """
    GET  /api/v1/resumes/   ← My resumes
    POST /api/v1/resumes/   ← Upload new (multipart)
    """

    permission_classes = [IsSeeker]
    parser_classes = [MultiPartParser, FormParser]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ResumeUploadSerializer
        return ResumeListSerializer

    def get_queryset(self):
        return Resume.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = ResumeUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resume = ResumeService.create_resume(
            user=request.user,
            name=serializer.validated_data["name"],
            file_obj=serializer.validated_data["file"],
            set_as_primary=serializer.validated_data.get("set_as_primary", False),
        )

        return Response(
            ResumeDetailSerializer(resume).data,
            status=status.HTTP_202_ACCEPTED,  # 202 = accepted, processing async
        )


class ResumeDetailView(generics.RetrieveDestroyAPIView):
    """
    GET    /api/v1/resumes/<uuid:public_id>/
    DELETE /api/v1/resumes/<uuid:public_id>/   ← Soft delete
    """

    serializer_class = ResumeDetailSerializer
    permission_classes = [IsSeeker]
    lookup_field = "public_id"

    def get_queryset(self):
        return Resume.objects.filter(user=self.request.user)

    def perform_destroy(self, instance):
        ResumeService.delete_resume(instance)


class SetPrimaryResumeView(APIView):
    """POST /api/v1/resumes/<uuid:public_id>/set-primary/"""

    permission_classes = [IsSeeker]

    def post(self, request, public_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )
        ResumeService.set_primary(resume)
        return Response(
            {
                "message": f'"{resume.name}" is now your primary resume.',
                "resume": ResumeDetailSerializer(resume).data,
            }
        )


class DownloadUrlView(APIView):
    """GET /api/v1/resumes/<uuid:public_id>/download-url/"""

    permission_classes = [IsSeeker]

    def get(self, request, public_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )
        url = ResumeService.get_download_url(resume, expires_in=300)
        if not url:
            return Response(
                {"error": "No file associated with this resume."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "url": url,
                "expires_in_seconds": 300,
            }
        )


class ParsedResumeView(APIView):
    """GET /api/v1/resumes/<uuid:public_id>/parsed/"""

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def get(self, request, public_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )

        if resume.status != Resume.Status.PARSED:
            return Response(
                {
                    "status": resume.status,
                    "message": "Resume is still processing or failed to parse.",
                    "failure_reason": resume.failure_reason,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        return Response(ResumeParsedSerializer(resume).data)


class ReparseResumeView(APIView):
    """POST /api/v1/resumes/<uuid:public_id>/reparse/"""

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def post(self, request, public_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )

        # Reset status so it goes through the pipeline again
        resume.status = Resume.Status.PENDING
        resume.failure_reason = ""
        resume.save(update_fields=["status", "failure_reason"])

        from .tasks import parse_resume_task

        parse_resume_task.delay(resume.id)

        return Response(
            {
                "message": "Resume queued for re-parsing.",
                "status": "pending",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AddResumeSkillView(APIView):
    """POST /api/v1/resumes/<uuid:public_id>/skills/"""

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def post(self, request, public_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )

        serializer = AddSkillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        skill_id = serializer.validated_data["skill_id"]

        from apps.skills.models import Skill

        skill = Skill.objects.get(id=skill_id)

        rs, created = ResumeSkill.objects.update_or_create(
            resume=resume,
            skill=skill,
            defaults={
                "confidence": 1.0,  # user-added = 100% confidence
                "source": ResumeSkill.Source.USER_ADDED,
                "is_user_added": True,
                "is_confirmed": True,
            },
        )

        return Response(
            ResumeSkillSerializer(rs).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class RemoveResumeSkillView(APIView):
    """DELETE /api/v1/resumes/<uuid:public_id>/skills/<int:skill_id>/"""

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def delete(self, request, public_id, skill_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )

        deleted, _ = ResumeSkill.objects.filter(
            resume=resume,
            skill_id=skill_id,
        ).delete()

        if not deleted:
            return Response({"error": "Skill not found."}, status=404)

        return Response(status=204)


class ConfirmResumeSkillView(APIView):
    """POST /api/v1/resumes/<uuid:public_id>/skills/<int:skill_id>/confirm/"""

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def post(self, request, public_id, skill_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )

        rs = get_object_or_404(
            ResumeSkill,
            resume=resume,
            skill_id=skill_id,
        )
        rs.is_confirmed = True
        rs.save(update_fields=["is_confirmed"])

        # Mirror the confirmed skill onto the seeker profile.
        # Match scoring reads profile skills, so without this the user can
        # confirm every extracted skill and still get no match scores.
        from apps.seekers.models import SeekerSkill

        seeker_profile = getattr(request.user, "seeker_profile", None)
        if seeker_profile:
            SeekerSkill.objects.get_or_create(
                seeker=seeker_profile,
                skill=rs.skill,
            )

        return Response({"message": "Skill confirmed."})


class AtsScoreView(APIView):
    """GET /api/v1/resumes/<uuid:public_id>/ats-score/"""

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def get(self, request, public_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )

        if resume.status != Resume.Status.PARSED:
            return Response(
                {
                    "status": resume.status,
                    "message": "Parsing not complete yet.",
                },
                status=202,
            )

        # Generate actionable suggestions from failed checks
        suggestions = []
        for check, data in resume.ats_breakdown.items():
            if not data.get("passed"):
                if "reason" in data:
                    suggestions.append(data["reason"])
                else:
                    suggestions.append(f"Improve: {check}")

        return Response(
            {
                "ats_score": resume.ats_score,
                "rating": get_ats_rating(resume.ats_score),
                "breakdown": resume.ats_breakdown,
                "suggestions": suggestions,
            }
        )


def get_ats_rating(score):
    """Convert a numeric ATS score into a human-readable label."""
    if score >= 80:
        return "Excellent"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Fair"
    return "Poor"


# An analysis that has not finished within this long is not coming: the task
# retries three times over a few minutes, so anything beyond it has given up.
ADVANCED_ATS_PATIENCE = timedelta(minutes=30)


def advanced_ats_state(resume):
    """
    Why there is no advanced ATS result yet, in words that are true.

    One field used to answer this - the absence of a result - and it cannot
    tell four different situations apart. Each returns its own state so the
    frontend can decide between "wait" and "offer the retry button".
    """
    if resume.status == Resume.Status.FAILED:
        return (
            "parse_failed",
            "This resume could not be read, so it cannot be analysed. Try uploading it again.",
        )

    if resume.status != Resume.Status.PARSED:
        return (
            "parsing",
            "The resume is still being read. The ATS analysis starts once that finishes.",
        )

    if resume.advanced_ats_queued_at is None:
        return (
            "never_started",
            "This resume has not been analysed yet. Ask for an analysis to get your ATS score.",
        )

    if timezone.now() - resume.advanced_ats_queued_at > ADVANCED_ATS_PATIENCE:
        return (
            "gave_up",
            "The analysis did not finish. Ask for it again, and tell us if it keeps failing.",
        )

    return ("running", "The ATS analysis is running. Check back in a moment.")


class AdvancedAtsView(APIView):
    """GET /api/v1/resumes/<uuid:public_id>/advanced-ats/"""

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def get(self, request, public_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )

        if not resume.advanced_ats_analyzed_at:
            state, message = advanced_ats_state(resume)
            return Response(
                {
                    "has_analysis": False,
                    "state": state,
                    "message": message,
                    # True only when POST re-analyze-ats/ would actually help.
                    "can_retry": state in ("never_started", "gave_up"),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        return Response(
            {
                "has_analysis": True,
                "analyzed_at": resume.advanced_ats_analyzed_at,
                "score": resume.advanced_ats_score,
                "breakdown": resume.advanced_ats_breakdown,
            }
        )


class ReAnalyzeAdvancedAtsView(APIView):
    """POST /api/v1/resumes/<uuid:public_id>/re-analyze-ats/"""

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def post(self, request, public_id):
        resume = get_object_or_404(
            Resume,
            public_id=public_id,
            user=request.user,
            is_deleted=False,
        )

        if resume.status != Resume.Status.PARSED:
            return Response(
                {"error": "The resume must finish parsing first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .tasks import queue_advanced_ats

        # Records the queue time as well, so the GET endpoint reports this as
        # running rather than as never started.
        queue_advanced_ats(resume)

        return Response(
            {"message": "Advanced ATS analysis queued."},
            status=status.HTTP_202_ACCEPTED,
        )


class ApplicationJdMatchView(APIView):
    """
    GET /api/v1/applications/<int:pk>/jd-match/

    Scores the attached resume against this specific job description.
    Computed on demand — job descriptions change, so caching would go stale.
    """

    permission_classes = [IsSeeker, HasResumeAiAnalysis]

    def get(self, request, pk):
        from apps.applications.models import Application
        from apps.skills.models import Skill

        from .ats_advanced import run_full_analysis

        application = get_object_or_404(
            Application,
            pk=pk,
            seeker=request.user.seeker_profile,  # ADJUST if named differently
        )

        # Applications store only a resume URL snapshot, not a foreign key,
        # so score the seeker's current primary resume against this job.
        resume = (
            Resume.objects.filter(
                user=request.user,
                status=Resume.Status.PARSED,
                is_deleted=False,
            )
            .order_by("-is_primary", "-created_at")
            .first()
        )

        if resume is None or not resume.extracted_text:
            return Response(
                {"error": "You do not have a parsed resume to match against."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        skill_names = set(
            Skill.objects.filter(is_approved=True, is_deprecated=False).values_list(
                "name", flat=True
            )
        )

        job = application.job
        # The description is free text and often thin or messy. The real
        # requirements live in the structured skill relations, so fold them
        # into the text the matcher sees.
        required = list(job.required_skills.values_list("name", flat=True))
        nice_to_have = list(job.nice_to_have_skills.values_list("name", flat=True))

        jd_text = "\n\n".join(
            filter(
                None,
                [
                    job.title,
                    job.description,
                    "Required skills: " + ", ".join(required) if required else None,
                    ("Nice to have: " + ", ".join(nice_to_have) if nice_to_have else None),
                ],
            )
        )

        result = run_full_analysis(
            resume_text=resume.extracted_text,
            jd_text=jd_text,
            skill_names=skill_names,
        )

        return Response(
            {
                "application_id": application.id,
                "job_title": job.title,
                "analysis": result,
            }
        )


class AtsBestPracticesView(APIView):
    """GET /api/v1/ats/best-practices/ — static guidance, no computation."""

    permission_classes = [permissions.IsAuthenticated]

    TIPS = [
        {
            "category": "Action Verbs",
            "do": [
                "Start each bullet with a strong verb: led, built, " "optimized, delivered.",
                "Vary the verbs across leadership, building and improvement.",
            ],
            "avoid": [
                'Filler openings such as "responsible for" or "helped with".',
                "Repeating the same verb in every bullet.",
            ],
        },
        {
            "category": "Quantify Achievements",
            "do": [
                'Attach numbers: "increased revenue 25%", "team of 8".',
                "Aim for at least 30% of bullets to carry a metric.",
            ],
            "avoid": [
                'Vague claims like "improved performance" with no figure.',
                "Listing duties instead of outcomes.",
            ],
        },
        {
            "category": "Language Quality",
            "do": [
                'Write in the active voice: "I designed the system".',
                "Spell-check, and keep technical terms consistent.",
            ],
            "avoid": [
                'Passive constructions: "the system was designed by me".',
                'Common slips such as "acheived" for "achieved".',
            ],
        },
        {
            "category": "Matching the Job Description",
            "do": [
                "Mirror the exact terms the posting uses.",
                "Tailor the resume for the roles you care most about.",
            ],
            "avoid": [
                "Keyword stuffing with skills you do not have.",
                "Sending one identical resume everywhere.",
            ],
        },
        {
            "category": "ATS-Safe Formatting",
            "do": [
                "Use standard fonts and clear section headings.",
                "Export as a text-based PDF, not a scan or screenshot.",
            ],
            "avoid": [
                "Tables, columns and text boxes, which parsers misread.",
                "Putting key details in headers or footers.",
            ],
        },
    ]

    def get(self, request):
        return Response({"tips": self.TIPS})
