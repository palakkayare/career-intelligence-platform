from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.payments.permissions import HasFeature
from apps.seekers.models import SeekerProfile

from .candidate_serializers import (
    CandidateDetailSerializer,
    CandidatePreviewSerializer,
    CandidateSearchInputSerializer,
    CandidateViewHistorySerializer,
    RecruiterCreditsSerializer,
    WhoViewedMeSerializer,
)
from .candidate_services import CandidateProfileService, CandidateSearchService
from .models import CandidateView, RecruiterCredits
from .permissions import IsRecruiter
from apps.core.throttles import SearchThrottle
# Only plans that include this feature key may search candidates
HasCandidateSearch = HasFeature.create('candidate_search')


def _searchable_seeker_or_404(public_id):
    """Fetch a seeker who is currently discoverable, else 404."""
    return get_object_or_404(
        SeekerProfile.discoverable(),
        public_id=public_id,
    )


class CandidateSearchView(APIView):
    """POST /api/v1/candidates/search/"""

    permission_classes = [IsRecruiter, HasCandidateSearch]
    throttle_classes = [SearchThrottle]

    def post(self, request):
        serializer = CandidateSearchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        recruiter = request.user.recruiter_profile

        # Resolve the optional target job UUID to a primary key
        target_job_id = None
        if data.get('target_job_uuid'):
            job = Job.objects.filter(
                public_id=data['target_job_uuid'], is_deleted=False,
            ).first()
            if job and job.posted_by_id != recruiter.id:
                return Response(
                    {'detail': 'You can only rank candidates against your own jobs.'},
                    status=403,
                )
            if job:
                target_job_id = job.id

        result = CandidateSearchService.search(
            recruiter=recruiter,
            filters={
                'skill_ids': data.get('skill_ids', []),
                'experience_years_min': data.get('experience_years_min'),
                'experience_years_max': data.get('experience_years_max'),
                'location_city': data.get('location_city'),
                'q': data.get('q'),
            },
            target_job_id=target_job_id,
            page=data.get('page', 1),
            page_size=data.get('page_size', 20),
        )

        results = CandidatePreviewSerializer(
            result['seekers'],
            many=True,
            context={'match_scores_map': result['match_scores_map']},
        )

        return Response({
            'total': result['total'],
            'page': result['page'],
            'page_size': result['page_size'],
            'has_next': result['has_next'],
            'results': results.data,
        })


class CandidateDetailView(APIView):
    """GET /api/v1/candidates/<uuid:public_id>/"""

    permission_classes = [IsRecruiter, HasCandidateSearch]

    def get(self, request, public_id):
        recruiter = request.user.recruiter_profile
        seeker = _searchable_seeker_or_404(public_id)

        target_job_id = None
        target_job_uuid = request.query_params.get('target_job_uuid')
        if target_job_uuid:
            job = Job.objects.filter(
                public_id=target_job_uuid, posted_by=recruiter,
            ).first()
            if job:
                target_job_id = job.id

        result = CandidateProfileService.get_profile(
            recruiter=recruiter,
            seeker=seeker,
            target_job_id=target_job_id,
        )

        serializer = CandidateDetailSerializer(
            seeker,
            context={'contact_revealed': result['contact_revealed']},
        )
        return Response(serializer.data)


class RevealContactView(APIView):
    """
    POST /api/v1/candidates/<uuid:public_id>/reveal/
    Spends one credit, unless this seeker was already revealed.
    """

    permission_classes = [IsRecruiter, HasCandidateSearch]

    def post(self, request, public_id):
        seeker = _searchable_seeker_or_404(public_id)

        result = CandidateProfileService.reveal_contact(
            recruiter=request.user.recruiter_profile,
            seeker=seeker,
        )

        serializer = CandidateDetailSerializer(
            result['seeker'],
            context={'contact_revealed': True},
        )
        return Response({
            'already_revealed': result['already_revealed'],
            'credits_remaining': result['credits_remaining'],
            'candidate': serializer.data,
        })


class MyCreditsView(APIView):
    """GET /api/v1/candidates/credits/me/"""

    permission_classes = [IsRecruiter]

    def get(self, request):
        credits, _ = RecruiterCredits.objects.get_or_create(
            recruiter=request.user.recruiter_profile,
            defaults={'monthly_reveal_limit': 0},
        )

        # Lazy reset so the balance is correct even if Beat has not run
        if credits.is_cycle_expired():
            credits.reset_cycle()

        return Response(RecruiterCreditsSerializer(credits).data)


class MyViewHistoryView(generics.ListAPIView):
    """GET /api/v1/candidates/views/me/"""

    serializer_class = CandidateViewHistorySerializer
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        return (
            CandidateView.objects
            .filter(recruiter=self.request.user.recruiter_profile)
            .select_related('seeker__user')
            .order_by('-created_at')[:200]
        )


class WhoViewedMeView(generics.ListAPIView):
    """GET /api/v1/seekers/me/who-viewed/  (seeker side)"""

    serializer_class = WhoViewedMeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'seeker_profile'):
            return CandidateView.objects.none()

        return (
            CandidateView.objects
            .filter(seeker=self.request.user.seeker_profile)
            # Search-result impressions are noise for the seeker
            .exclude(view_kind=CandidateView.ViewKind.SEARCH_RESULT)
            .select_related('recruiter__user', 'recruiter__company')
            .order_by('-created_at')[:50]
        )