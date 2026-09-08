from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.payments.permissions import HasMatchScore, HasCandidateSearch
from apps.recruiters.permissions import IsRecruiter
from apps.seekers.models import SeekerProfile
from apps.seekers.permissions import IsSeeker
from .models import MatchScore, SavedCandidate
from .serializers import (
    MatchScoreDetailSerializer,
    CandidateMatchSerializer,
    SavedCandidateSerializer,
    SaveCandidateInputSerializer,
)
from .services import MatchScoreService, RecommendationService


# ─── SEEKER SIDE ───

class JobMatchScoreView(APIView):
    """
    GET /api/v1/jobs/<uuid:public_id>/match-score/
    Pro seeker only. Returns match score breakdown for a specific job.
    """
    permission_classes = [IsSeeker, HasMatchScore]

    def get(self, request, public_id):
        job = get_object_or_404(
            Job,
            public_id=public_id,
            status=Job.Status.ACTIVE,
            is_deleted=False,
        )

        match = MatchScoreService.get_or_compute(
            seeker=request.user.seeker_profile,
            job=job,
        )

        return Response(MatchScoreDetailSerializer(match).data)


class RecommendedJobsView(generics.ListAPIView):
    """
    GET /api/v1/match/recommended-jobs/
    Pro seeker only. Top jobs by match score.
    """
    serializer_class = MatchScoreDetailSerializer
    permission_classes = [IsSeeker, HasMatchScore]
    pagination_class = None

    def get_queryset(self):
        limit = int(self.request.query_params.get('limit', 20))
        min_score = float(self.request.query_params.get('min_score', 50))
        return RecommendationService.top_jobs_for_seeker(
            seeker=self.request.user.seeker_profile,
            limit=min(limit, 50),
            min_score=min_score,
        )
        
# ─── RECRUITER SIDE ───

class JobRecommendedCandidatesView(generics.ListAPIView):
    """
    GET /api/v1/jobs/<uuid:public_id>/recommended-candidates/
    Business recruiter only.
    """
    serializer_class = CandidateMatchSerializer
    permission_classes = [IsRecruiter, HasCandidateSearch]
    pagination_class = None

    def get_queryset(self):
        public_id = self.kwargs['public_id']
        job = get_object_or_404(
            Job,
            public_id=public_id,
            is_deleted=False,
        )

        # Verify this recruiter owns the job
        if job.posted_by_id != self.request.user.recruiter_profile.id:
            self.permission_denied(self.request)

        limit = int(self.request.query_params.get('limit', 20))
        min_score = float(self.request.query_params.get('min_score', 50))
        return RecommendationService.top_candidates_for_job(
            job=job,
            limit=min(limit, 100),
            min_score=min_score,
        )


class SavedCandidatesView(generics.ListCreateAPIView):
    """
    GET  /api/v1/match/saved-candidates/
    POST /api/v1/match/saved-candidates/ { seeker_public_id, notes }
    """
    serializer_class = SavedCandidateSerializer
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        return SavedCandidate.objects.filter(
            recruiter=self.request.user.recruiter_profile,
        ).select_related('seeker__user')

    def post(self, request, *args, **kwargs):
        input_serializer = SaveCandidateInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        seeker = get_object_or_404(
            SeekerProfile,
            user__public_id=input_serializer.validated_data['seeker_public_id'],
        )

        saved, created = SavedCandidate.objects.get_or_create(
            recruiter=request.user.recruiter_profile,
            seeker=seeker,
            defaults={
                'notes': input_serializer.validated_data.get('notes', ''),
            },
        )

        return Response(
            SavedCandidateSerializer(saved).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class SavedCandidateDetailView(generics.DestroyAPIView):
    """DELETE /api/v1/match/saved-candidates/<id>/"""
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        return SavedCandidate.objects.filter(
            recruiter=self.request.user.recruiter_profile,
        )