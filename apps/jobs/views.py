from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import FlexiblePagination
from apps.core.throttles import SearchThrottle
from apps.recruiters.permissions import IsRecruiter
from apps.seekers.permissions import IsSeeker

from .filters import JobFilterSet
from .models import Job, JobCategory, SavedJob, SavedSearch, SearchHistory, Tag
from .permissions import IsAdminUser, IsJobOwnerOrReadOnly
from .search import JobSearchService
from .serializers import (
    JobCategorySerializer,
    JobCreateUpdateSerializer,
    JobDetailSerializer,
    JobListSerializer,
    PublicJobDetailSerializer,
    SavedJobSerializer,
    SavedSearchSerializer,
    SaveJobSerializer,
    SearchHistorySerializer,
    TagSerializer,
)
from .services import JobDuplicationService, JobStatusService

# ───── Categories & Tags (Public) ─────


class JobCategoryListView(generics.ListAPIView):
    """GET /api/v1/job-categories/ ← top-level only with children nested."""

    serializer_class = JobCategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return JobCategory.objects.filter(is_active=True, parent__isnull=True)


class TagListView(generics.ListAPIView):
    """GET /api/v1/job-tags/?q=..."""

    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = Tag.objects.all().order_by("-use_count", "name")
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q.lower())
        return qs[:30]


# ───── Public Job Listing ─────


class PublicJobListView(generics.ListAPIView):
    """
    GET /api/v1/jobs/ ← ACTIVE jobs only.

    Open to anyone. A job board behind a login has no organic traffic and no
    shareable links, which removes most of the point of posting on it -
    Feature 20 counts SEO as a revenue channel and it cannot work otherwise.

    Only listings are public. Applying, saving, match scores and everything
    else still needs a login.
    """

    serializer_class = JobListSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [SearchThrottle]

    def get_queryset(self):
        return (
            Job.objects.filter(status=Job.Status.ACTIVE, is_deleted=False)
            .select_related("company", "category")
            .prefetch_related("required_skills")
            .order_by("-activated_at")
        )


class JobDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/jobs/<uuid>/

    Public, so a shared link opens for someone who is not signed in.
    Anonymous readers get a narrower serializer - see get_serializer_class.
    """

    permission_classes = [permissions.AllowAny]
    lookup_field = "public_id"

    def get_serializer_class(self):
        if self.request.user.is_authenticated:
            return JobDetailSerializer
        return PublicJobDetailSerializer

    def get_queryset(self):
        # Recruiters can see their own (any status). Others only ACTIVE.
        user = self.request.user
        base = Job.objects.select_related("company", "category", "posted_by").filter(
            is_deleted=False
        )
        if hasattr(user, "recruiter_profile"):
            return base.filter(Q(status=Job.Status.ACTIVE) | Q(posted_by=user.recruiter_profile))
        return base.filter(status=Job.Status.ACTIVE)


class IncrementJobViewView(APIView):
    """POST /api/v1/jobs/<uuid>/view/ ← Atomic increment."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, public_id):
        updated = Job.objects.filter(
            public_id=public_id,
            status=Job.Status.ACTIVE,
            is_deleted=False,
        ).update(view_count=F("view_count") + 1)

        if not updated:
            return Response({"error": "Job not found."}, status=404)
        return Response({"success": True})


# ───── Recruiter-side ─────


class MyJobListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/jobs/my/  ← All my jobs (any status)
    POST /api/v1/jobs/     ← Create draft
    """

    permission_classes = [IsRecruiter]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return JobCreateUpdateSerializer
        return JobListSerializer

    def get_queryset(self):
        recruiter = self.request.user.recruiter_profile
        return (
            Job.objects.filter(posted_by=recruiter)
            .select_related("company", "category")
            .prefetch_related("required_skills")
            .order_by("-created_at")
        )

    def get_serializer_context(self):
        return {"request": self.request}


class JobUpdateDestroyView(generics.UpdateAPIView, generics.DestroyAPIView):
    """
    PATCH  /api/v1/jobs/<uuid>/  ← Only draft/rejected by owner
    DELETE /api/v1/jobs/<uuid>/  ← Soft delete
    """

    serializer_class = JobCreateUpdateSerializer
    permission_classes = [IsRecruiter, IsJobOwnerOrReadOnly]
    lookup_field = "public_id"

    def get_queryset(self):
        return Job.objects.filter(is_deleted=False)

    def perform_update(self, serializer):
        instance = self.get_object()
        if not instance.can_be_edited_by(self.request.user):
            raise PermissionDenied("Only DRAFT or REJECTED jobs can be edited.")
        serializer.save()

    def perform_destroy(self, instance):
        instance.soft_delete()

    def get_serializer_context(self):
        return {"request": self.request}


# ───── Action Endpoints ─────


class _ActionView(APIView):
    """Base for action endpoints — consistent permission + lookup."""

    permission_classes = [IsRecruiter]

    def _get_my_job(self, public_id):
        recruiter = self.request.user.recruiter_profile
        return get_object_or_404(
            Job,
            public_id=public_id,
            posted_by=recruiter,
            is_deleted=False,
        )


class SubmitJobView(_ActionView):
    """POST /api/v1/jobs/<uuid>/submit/"""

    def post(self, request, public_id):
        job = self._get_my_job(public_id)
        JobStatusService.submit(job)
        return Response(
            {
                "message": "Job submitted.",
                "status": job.status,
            }
        )


class CloseJobView(_ActionView):
    """POST /api/v1/jobs/<uuid>/close/"""

    def post(self, request, public_id):
        job = self._get_my_job(public_id)
        JobStatusService.close(job)
        return Response({"message": "Job closed.", "status": job.status})


class DuplicateJobView(_ActionView):
    """POST /api/v1/jobs/<uuid>/duplicate/"""

    def post(self, request, public_id):
        original = self._get_my_job(public_id)
        new_job = JobDuplicationService.duplicate(
            original,
            request.user.recruiter_profile,
        )
        return Response(
            JobDetailSerializer(new_job).data,
            status=201,
        )


class BackToDraftView(_ActionView):
    """POST /api/v1/jobs/<uuid>/back-to-draft/ ← For rejected jobs."""

    def post(self, request, public_id):
        job = self._get_my_job(public_id)
        JobStatusService.back_to_draft(job)
        return Response({"message": "Moved to draft.", "status": job.status})


# ───── Admin Side ─────


class AdminPendingJobsView(generics.ListAPIView):
    """GET /api/v1/admin/jobs/pending/"""

    serializer_class = JobListSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        return (
            Job.objects.filter(
                status=Job.Status.PENDING_APPROVAL,
                is_deleted=False,
            )
            .select_related("company", "posted_by__user")
            .order_by("submitted_at")
        )


class AdminApproveJobView(APIView):
    """POST /api/v1/admin/jobs/<uuid>/approve/"""

    permission_classes = [IsAdminUser]

    def post(self, request, public_id):
        job = get_object_or_404(Job, public_id=public_id, is_deleted=False)
        JobStatusService.approve(job, actor=request.user)
        return Response({"message": "Job approved and live.", "status": job.status})


class AdminRejectJobView(APIView):
    """POST /api/v1/admin/jobs/<uuid>/reject/"""

    permission_classes = [IsAdminUser]

    def post(self, request, public_id):
        job = get_object_or_404(Job, public_id=public_id, is_deleted=False)
        reason = request.data.get("reason", "").strip()
        JobStatusService.reject(job, actor=request.user, reason=reason)
        return Response({"message": "Job rejected.", "status": job.status})


class JobSearchView(generics.ListAPIView):
    """
    GET /api/v1/jobs/search/

    Query params:
    - q: search keywords
    - location, employment_type, work_arrangement, salary_min, salary_max,
      skills, industry, category, experience, verified_company, posted_within_days
    - sort: relevance | date | salary | oldest
    - page, page_size
    """

    serializer_class = JobListSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [SearchThrottle]
    filter_backends = [DjangoFilterBackend]
    filterset_class = JobFilterSet
    pagination_class = FlexiblePagination

    def get_queryset(self):
        query_text = self.request.query_params.get("q", "").strip()
        sort = self.request.query_params.get("sort", "relevance")

        # Match-score sorting only means something for a seeker; a recruiter
        # or an anonymous visitor has no scores of their own.
        seeker = getattr(self.request.user, "seeker_profile", None)

        return JobSearchService.build_queryset(
            query_text=query_text,
            sort=sort,
            seeker=seeker,
        )

    def list(self, request, *args, **kwargs):
        # Get filtered, paginated results
        response = super().list(request, *args, **kwargs)
        # Save to history (only for authenticated users with non-trivial query)
        self._record_history(request, response.data.get("count", 0))
        return response

    def _record_history(self, request, result_count):
        """Save search to user's history (auto-prune to last 10)."""
        # Search is open to anyone now, and there is nobody to attribute an
        # anonymous search to.
        if not request.user.is_authenticated:
            return

        query_text = request.query_params.get("q", "").strip()

        # Capture filters (exclude pagination params)
        filters = {
            k: v
            for k, v in request.query_params.items()
            if k not in ("q", "sort", "page", "page_size")
        }

        # Skip if both empty
        if not query_text and not filters:
            return

        SearchHistory.objects.create(
            user=request.user,
            query_text=query_text,
            filters=filters,
            result_count=result_count,
        )

        # Prune to last 10
        cutoff = (
            SearchHistory.objects.filter(user=request.user)
            .order_by("-created_at")
            .values_list("id", flat=True)[SearchHistory.MAX_PER_USER :]
        )
        SearchHistory.objects.filter(id__in=list(cutoff)).delete()


# ───── Saved Searches ─────


class SavedSearchListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/jobs/saved-searches/
    POST /api/v1/jobs/saved-searches/
    Body: { "name": "Remote Python", "query_text": "python", "filters": {...} }
    """

    serializer_class = SavedSearchSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return SavedSearch.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SavedSearchDestroyView(generics.DestroyAPIView):
    """DELETE /api/v1/jobs/saved-searches/<id>/"""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SavedSearch.objects.filter(user=self.request.user)


class ExecuteSavedSearchView(APIView):
    """
    POST /api/v1/jobs/saved-searches/<id>/execute/
    Updates last_executed_at and returns the URL to run the search.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            saved = SavedSearch.objects.get(pk=pk, user=request.user)
        except SavedSearch.DoesNotExist:
            return Response({"error": "Not found."}, status=404)

        saved.last_executed_at = timezone.now()
        saved.save(update_fields=["last_executed_at"])

        # Build query params for the search URL
        params = dict(saved.filters)
        if saved.query_text:
            params["q"] = saved.query_text

        return Response(
            {
                "name": saved.name,
                "query_params": params,
                "redirect_url": "/api/v1/jobs/search/",
                "last_executed_at": saved.last_executed_at,
            }
        )


# ───── Search History ─────


class SearchHistoryView(generics.ListAPIView):
    """
    GET    /api/v1/jobs/search-history/ ← Last 10
    DELETE /api/v1/jobs/search-history/ ← Clear all
    """

    serializer_class = SearchHistorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return SearchHistory.objects.filter(user=self.request.user)[:10]

    def delete(self, request, *args, **kwargs):
        SearchHistory.objects.filter(user=request.user).delete()
        return Response({"message": "History cleared."})


# ─── Saved jobs (bookmarks) ───


class SaveJobView(APIView):
    """
    POST /api/v1/jobs/<uuid:job_uuid>/save/

    Idempotent: saving an already-saved job updates the note instead of
    failing, which is what a "save" button pressed twice should do.
    """

    permission_classes = [IsSeeker]

    def post(self, request, job_uuid):
        job = get_object_or_404(Job, public_id=job_uuid, is_deleted=False)

        serializer = SaveJobSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        saved, created = SavedJob.objects.update_or_create(
            user=request.user,
            job=job,
            defaults={"note": serializer.validated_data.get("note", "")},
        )

        return Response(
            SavedJobSerializer(saved).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class UnsaveJobView(APIView):
    """DELETE /api/v1/jobs/<uuid:job_uuid>/save/"""

    permission_classes = [IsSeeker]

    def delete(self, request, job_uuid):
        job = get_object_or_404(Job, public_id=job_uuid)
        deleted, _ = SavedJob.objects.filter(user=request.user, job=job).delete()

        if not deleted:
            return Response(
                {"detail": "This job is not in your saved list."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SavedJobListView(generics.ListAPIView):
    """
    GET /api/v1/jobs/saved/

    Deleted jobs are filtered out, but bookmarks on closed or expired
    postings are kept: the seeker saved it, and seeing what happened to it is
    more useful than having it silently vanish.
    """

    serializer_class = SavedJobSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        return (
            SavedJob.objects.filter(user=self.request.user, job__is_deleted=False)
            .select_related("job", "job__company", "job__category")
            .prefetch_related("job__required_skills")
        )
