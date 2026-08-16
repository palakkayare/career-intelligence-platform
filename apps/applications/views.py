from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.seekers.permissions import IsSeeker
from apps.recruiters.permissions import IsRecruiter
from .models import Application
from .permissions import IsApplicationOwner, IsApplicationRecruiter
from .serializers import (
    ApplyJobSerializer,
    ApplicationSeekerSerializer,
    ApplicationRecruiterSerializer,
    ApplicationStatusHistorySerializer,
    StatusUpdateSerializer,
    RecruiterNotesSerializer,
)
from .services import (
    ApplicationCreationService,
    ApplicationStatusService,
    QuotaService,
)


# ───────── SEEKER SIDE ──────────

class ApplyToJobView(APIView):
    """
    POST /api/v1/jobs/<uuid:job_uuid>/apply/
    """
    permission_classes = [IsSeeker]

    def post(self, request, job_uuid):
        job = get_object_or_404(Job, public_id=job_uuid, is_deleted=False)
        serializer = ApplyJobSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        application = ApplicationCreationService.create(
            seeker_profile=request.user.seeker_profile,
            job=job,
            cover_letter=serializer.validated_data.get('cover_letter', ''),
            resume_url=serializer.validated_data.get('resume_url', ''),
        )

        return Response(
            ApplicationSeekerSerializer(application).data,
            status=status.HTTP_201_CREATED,
        )


class MyApplicationsView(generics.ListAPIView):
    """
    GET /api/v1/applications/me/
    Optional: ?status=submitted (filter by status)
    """
    serializer_class = ApplicationSeekerSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        # Use all_objects to include withdrawn (is_deleted=True).
        # The serializer walks into company.industry, job.category and the job's
        # skills, so those relations are joined/prefetched here as well —
        # otherwise each application triggers its own lookup for them.
        qs = (
            Application.all_objects
            .filter(seeker=self.request.user.seeker_profile)
            .select_related(
                'job',
                'job__company',
                'job__company__industry',
                'job__category',
            )
            .prefetch_related(
                'job__required_skills',
                # nice_to_have_skills and tags are NOT exposed by
                # ApplicationSeekerSerializer — prefetching them cost one
                # query each for data that never reached the response.
            )
        )
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by('-submitted_at')


class MyApplicationDetailView(generics.RetrieveAPIView):
    """GET /api/v1/applications/me/<id>/"""
    serializer_class = ApplicationSeekerSerializer
    permission_classes = [IsSeeker, IsApplicationOwner]

    def get_queryset(self):
        return Application.all_objects.select_related('job', 'job__company')


class WithdrawApplicationView(APIView):
    """POST /api/v1/applications/me/<id>/withdraw/"""
    permission_classes = [IsSeeker, IsApplicationOwner]

    def post(self, request, pk):
        application = get_object_or_404(Application.all_objects, pk=pk)
        self.check_object_permissions(request, application)

        ApplicationStatusService.update_status(
            application,
            new_status=Application.Status.WITHDRAWN,
            actor=request.user,
            notes='Withdrawn by candidate.',
        )
        return Response({
            'message': 'Application withdrawn.',
            'status': application.status,
        })


class ApplicationHistoryView(generics.ListAPIView):
    """
    GET /api/v1/applications/me/<id>/history/
    GET /api/v1/applications/<id>/history/ (recruiter side)
    """
    serializer_class = ApplicationStatusHistorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        application = get_object_or_404(Application.all_objects, pk=self.kwargs['pk'])

        # Permission check
        user = self.request.user
        is_owner = (
            user.role == 'seeker'
            and application.seeker.user_id == user.id
        )
        is_recruiter = (
            user.role == 'recruiter'
            and hasattr(user, 'recruiter_profile')
            and application.job.posted_by_id == user.recruiter_profile.id
        )
        if not (is_owner or is_recruiter):
            self.permission_denied(self.request)

        return application.status_history.all()


class QuotaStatusView(APIView):
    """GET /api/v1/applications/me/quota/"""
    permission_classes = [IsSeeker]

    def get(self, request):
        usage = QuotaService.get_usage(request.user)
        return Response({
            **usage,
            'window_days': 30,
            'message': (
                f"You have {usage['remaining']} applications remaining "
                f"in the next 30 days." if usage['remaining'] > 0
                else "Free tier limit reached. Upgrade to Pro for unlimited."
            ),
        })
        
# ───────── RECRUITER SIDE ──────────

class JobApplicationsView(generics.ListAPIView):
    """
    GET /api/v1/jobs/<uuid:job_uuid>/applications/
    Recruiter views applications to their job.
    Optional: ?status=submitted&include_withdrawn=true
    """
    serializer_class = ApplicationRecruiterSerializer
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        job_uuid = self.kwargs['job_uuid']
        job = get_object_or_404(Job, public_id=job_uuid)

        # Verify recruiter owns this job
        if job.posted_by_id != self.request.user.recruiter_profile.id:
            self.permission_denied(self.request)

        # Use all_objects to include withdrawn?
        include_withdrawn = self.request.query_params.get('include_withdrawn') == 'true'
        manager = Application.all_objects if include_withdrawn else Application.objects

        qs = (
            manager
            .filter(job=job)
            .select_related('seeker', 'seeker__user', 'job')
        )
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by('-submitted_at')


class RecruiterApplicationDetailView(generics.RetrieveAPIView):
    """GET /api/v1/applications/<id>/ (recruiter view with notes)"""
    serializer_class = ApplicationRecruiterSerializer
    permission_classes = [IsRecruiter, IsApplicationRecruiter]

    def get_queryset(self):
        return Application.all_objects.select_related('seeker__user', 'job__company')


class UpdateApplicationStatusView(APIView):
    """
    POST /api/v1/applications/<id>/status/
    Body: { status: 'shortlisted', notes: 'Strong portfolio.' }
    """
    permission_classes = [IsRecruiter, IsApplicationRecruiter]

    def post(self, request, pk):
        application = get_object_or_404(Application.all_objects, pk=pk)
        self.check_object_permissions(request, application)

        serializer = StatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ApplicationStatusService.update_status(
            application,
            new_status=serializer.validated_data['status'],
            actor=request.user,
            notes=serializer.validated_data.get('notes', ''),
        )
        return Response({
            'message': f"Status updated to {application.status}.",
            'status': application.status,
        })


class UpdateRecruiterNotesView(APIView):
    """
    POST /api/v1/applications/<id>/notes/
    Body: { recruiter_notes: '...' }
    """
    permission_classes = [IsRecruiter, IsApplicationRecruiter]

    def post(self, request, pk):
        application = get_object_or_404(Application.all_objects, pk=pk)
        self.check_object_permissions(request, application)

        serializer = RecruiterNotesSerializer(application, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({'message': 'Notes updated.'})