from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.permissions import HasFeature
from apps.seekers.permissions import IsSeeker

from .learning_services import LearningService
from .models import (
    CareerPathNode,
    LearningResource,
    SalarySubmission,
    SkillGapSnapshot,
    TargetRole,
    UserLearning,
)
from .path_services import CareerPathService
from .salary_services import SalaryService
from .serializers import (
    AnalyzeGapInputSerializer,
    CareerPathNodeDetailSerializer,
    CareerPathNodeListSerializer,
    CompleteLearningSerializer,
    FindPathInputSerializer,
    LearningResourceDetailSerializer,
    LearningResourceListSerializer,
    SalaryInsightsInputSerializer,
    SalarySubmissionDisplaySerializer,
    SalarySubmitSerializer,
    SnapshotSerializer,
    StartLearningInputSerializer,
    TargetRoleDetailSerializer,
    TargetRoleListSerializer,
    UpdateProgressSerializer,
    UserLearningSerializer,
)
from .services import SkillGapService

# Feature-flag permission built in Step 15
HasSkillGap = HasFeature.create("skill_gap")


# --- Target Roles (readable by any authenticated user) ---


class TargetRoleListView(generics.ListAPIView):
    """
    GET /api/v1/target-roles/
    Optional filter: ?category=engineering
    """

    serializer_class = TargetRoleListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = TargetRole.objects.filter(is_active=True).order_by(
            "sort_order",
            "name",
        )
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        return qs


class TargetRoleDetailView(generics.RetrieveAPIView):
    """GET /api/v1/target-roles/<slug>/"""

    serializer_class = TargetRoleDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = TargetRole.objects.filter(is_active=True)
    lookup_field = "slug"


# --- Skill Gap Analysis (Pro feature) ---


class AnalyzeGapView(APIView):
    """
    POST /api/v1/skill-gap/analyze/

    Body:
        {
            "target_role_slug": "senior-backend-developer",
            "save_snapshot": false,
            "label": ""
        }
    """

    permission_classes = [IsSeeker, HasSkillGap]

    def post(self, request):
        serializer = AnalyzeGapInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        slug = serializer.validated_data["target_role_slug"]
        save_snapshot = serializer.validated_data.get("save_snapshot", False)
        label = serializer.validated_data.get("label", "")

        target_role = get_object_or_404(TargetRole, slug=slug, is_active=True)
        seeker = request.user.seeker_profile

        analysis = SkillGapService.analyze(seeker, target_role)

        snapshot = None
        if save_snapshot:
            snapshot = SkillGapService.save_snapshot(
                seeker,
                target_role,
                label=label,
            )

        return Response(
            {
                **analysis,
                "snapshot_saved": snapshot is not None,
                "snapshot_public_id": str(snapshot.public_id) if snapshot else None,
            }
        )


class MyLatestGapView(APIView):
    """GET /api/v1/skill-gap/me/ - returns the most recent snapshot, if any."""

    permission_classes = [IsSeeker, HasSkillGap]

    def get(self, request):
        seeker = request.user.seeker_profile
        snapshot = (
            SkillGapSnapshot.objects.filter(seeker=seeker)
            .select_related("target_role")
            .order_by("-created_at")
            .first()
        )

        if not snapshot:
            return Response(
                {
                    "has_snapshot": False,
                    "message": ("No analysis yet. POST to /skill-gap/analyze/ to start."),
                }
            )

        return Response(
            {
                "has_snapshot": True,
                "snapshot": SnapshotSerializer(snapshot).data,
            }
        )


class MyGapHistoryView(generics.ListAPIView):
    """
    GET /api/v1/skill-gap/me/history/
    Optional filter: ?target_role_slug=senior-backend-developer
    """

    serializer_class = SnapshotSerializer
    permission_classes = [IsSeeker, HasSkillGap]
    pagination_class = None

    def get_queryset(self):
        seeker = self.request.user.seeker_profile
        qs = SkillGapSnapshot.objects.filter(
            seeker=seeker,
        ).select_related("target_role")

        target_slug = self.request.query_params.get("target_role_slug")
        if target_slug:
            qs = qs.filter(target_role__slug=target_slug)

        # Cap the history so the chart stays readable
        return qs.order_by("-created_at")[:24]


# ---------------------------------------------------------------------------
# Feature 13 - Learning Recommendations
# ---------------------------------------------------------------------------

# Recommendations reuse the skill_gap feature flag for now. When learning gets
# its own plan entitlement, swap this for HasFeature.create('learning_recs').
HasLearningRecs = HasFeature.create("skill_gap")


# --- Resources (browsable by any authenticated user, including free) ---


class LearningResourceListView(generics.ListAPIView):
    """
    GET /api/v1/learning/resources/
    Filters: ?kind=course&difficulty=beginner&is_free=true&q=python
    """

    serializer_class = LearningResourceListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (
            LearningResource.objects.filter(is_active=True)
            .select_related("provider")
            .prefetch_related("resource_skills__skill")
            .order_by("-is_endorsed", "-quality_score")
        )

        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)

        difficulty = self.request.query_params.get("difficulty")
        if difficulty:
            qs = qs.filter(difficulty=difficulty)

        is_free = self.request.query_params.get("is_free")
        if is_free == "true":
            qs = qs.filter(is_free=True)
        elif is_free == "false":
            qs = qs.filter(is_free=False)

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(title__icontains=q)

        return qs


class LearningResourceDetailView(generics.RetrieveAPIView):
    """GET /api/v1/learning/resources/<id>/"""

    serializer_class = LearningResourceDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = (
        LearningResource.objects.filter(is_active=True)
        .select_related("provider")
        .prefetch_related("resource_skills__skill")
    )


class SkillResourcesView(generics.ListAPIView):
    """
    GET /api/v1/learning/skills/<skill_id>/resources/
    Every resource that teaches one skill, ranked by quality.
    """

    serializer_class = LearningResourceListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return (
            LearningResource.objects.filter(
                resource_skills__skill_id=self.kwargs["skill_id"],
                is_active=True,
            )
            .select_related("provider")
            .prefetch_related("resource_skills__skill")
            .order_by("-is_endorsed", "-quality_score")
            .distinct()
        )


# --- Recommendations (Pro feature) ---


class MyRecommendationsView(APIView):
    """
    GET /api/v1/learning/recommendations/me/
    Optional: ?target_role_slug=senior-backend-developer
    """

    permission_classes = [IsSeeker, HasLearningRecs]

    def get(self, request):
        target_role_slug = request.query_params.get("target_role_slug")

        target_role = None
        if target_role_slug:
            target_role = get_object_or_404(
                TargetRole,
                slug=target_role_slug,
                is_active=True,
            )

        result = LearningService.get_recommendations(
            user=request.user,
            target_role=target_role,
        )

        # The service returns model instances; serialize them for the response
        for rec in result.get("recommendations", []):
            rec["resources"] = LearningResourceListSerializer(
                rec["resources"],
                many=True,
            ).data

        return Response(result)


# --- User progress tracking (open to any authenticated user) ---


class MyLearningsView(generics.ListAPIView):
    """
    GET /api/v1/learning/me/
    Optional: ?status=in_progress
    """

    serializer_class = UserLearningSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (
            UserLearning.objects.filter(user=self.request.user)
            .select_related("resource", "resource__provider")
            .prefetch_related("resource__resource_skills__skill")
        )

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs.order_by("-updated_at")


class StartLearningView(APIView):
    """
    POST /api/v1/learning/me/start/
    Body: { "resource_id": 5 }
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = StartLearningInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resource = get_object_or_404(
            LearningResource,
            id=serializer.validated_data["resource_id"],
            is_active=True,
        )

        learning = LearningService.start_learning(request.user, resource)

        return Response(
            UserLearningSerializer(learning).data,
            status=status.HTTP_201_CREATED,
        )


class UpdateProgressView(APIView):
    """
    PATCH /api/v1/learning/me/<id>/progress/
    Body: { "progress_pct": 50, "notes": "..." }
    """

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        learning = get_object_or_404(UserLearning, pk=pk, user=request.user)

        serializer = UpdateProgressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        LearningService.update_progress(
            learning,
            progress_pct=serializer.validated_data["progress_pct"],
            notes=serializer.validated_data.get("notes", ""),
        )

        return Response(UserLearningSerializer(learning).data)


class CompleteLearningView(APIView):
    """
    POST /api/v1/learning/me/<id>/complete/
    Body: { "user_rating": 5, "notes": "..." }
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        learning = get_object_or_404(UserLearning, pk=pk, user=request.user)

        serializer = CompleteLearningSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        LearningService.mark_completed(
            learning,
            user_rating=serializer.validated_data.get("user_rating"),
            notes=serializer.validated_data.get("notes", ""),
        )

        return Response(UserLearningSerializer(learning).data)


class DropLearningView(generics.DestroyAPIView):
    """DELETE /api/v1/learning/me/<id>/ - drop or unenroll."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserLearning.objects.filter(user=self.request.user)


# =============================================================================
# STEP 6 -- Append this to: apps/career_intel/views.py
#
# Required imports at the top of views.py (add only what is missing):
#     from rest_framework import generics, permissions, status
#     from rest_framework.response import Response
#     from rest_framework.views import APIView
#     from .salary_services import SalaryService
#     from .models import SalarySubmission
#     from .serializers import (
#         SalarySubmitSerializer,
#         SalaryInsightsInputSerializer,
#         SalarySubmissionDisplaySerializer,
#     )
#     # HasFeature already exists in this project.
# =============================================================================


# Feature-gate for the paid salary insights endpoints.
HasSalaryInsights = HasFeature.create("salary_insights")


class SubmitSalaryView(APIView):
    """
    POST /api/v1/salary/submit/

    Anonymous submission. The user is stored internally for de-duplication
    only and is never exposed through any aggregation endpoint.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SalarySubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.career_intel.salary_services import client_ip

        submission = SalaryService.submit(
            user=request.user,
            data=serializer.validated_data,
            ip_address=client_ip(request),
        )

        return Response(
            {
                "message": "Thank you for contributing. Your data stays anonymous.",
                "submission_id": submission.id,
            },
            status=status.HTTP_201_CREATED,
        )


class MySalarySubmissionsView(generics.ListAPIView):
    """
    GET /api/v1/salary/me/

    Lists the requesting user's own submissions. Visible to that user only.
    """

    serializer_class = SalarySubmissionDisplaySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SalarySubmission.objects.filter(user=self.request.user)


class DeleteMySalarySubmissionView(generics.DestroyAPIView):
    """
    DELETE /api/v1/salary/me/<id>/

    Scoped to the requesting user, so nobody can delete someone else's row.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SalarySubmission.objects.filter(user=self.request.user)


class SalaryInsightsView(APIView):
    """
    POST /api/v1/salary/insights/

    Privacy-preserving aggregation. Paid feature.
    Body example: { "role_title": "Backend Developer", "location_city": "Bangalore" }
    """

    permission_classes = [permissions.IsAuthenticated, HasSalaryInsights]

    def post(self, request):
        serializer = SalaryInsightsInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Drop blank values so they are not treated as real filters.
        filters = {
            key: value
            for key, value in serializer.validated_data.items()
            if value not in (None, "", [])
        }

        if not filters:
            return Response(
                {
                    "has_data": False,
                    "message": (
                        "Provide at least one filter, for example role_title or location_city."
                    ),
                }
            )

        result = SalaryService.get_insights(filters)
        return Response(result)


class MySalaryComparisonView(APIView):
    """
    GET /api/v1/salary/my-comparison/

    Compares the user's own salary against the market. Paid feature.
    """

    permission_classes = [permissions.IsAuthenticated, HasSalaryInsights]

    def get(self, request):
        result = SalaryService.get_user_comparison(request.user)
        return Response(result)


# =============================================================================
# STEP 6 -- Append this to: apps/career_intel/views.py
#
# Required imports at the top of views.py (add only what is missing):
#     from rest_framework import generics, permissions, status
#     from rest_framework.response import Response
#     from rest_framework.views import APIView
#     from .models import CareerPathNode, CareerPathEdge
#     from .path_services import CareerPathService
#     from .serializers import (
#         CareerPathNodeListSerializer,
#         CareerPathNodeDetailSerializer,
#         FindPathInputSerializer,
#     )
#     # HasFeature and IsSeeker already exist in this project.
#
# Do not skip these. Every NameError in Feature 14 came from pasting the class
# bodies without the imports listed above them.
# =============================================================================


# Feature-gate for the paid path-finding endpoints.
HasCareerPath = HasFeature.create("career_path")


class CareerPathNodeListView(generics.ListAPIView):
    """
    GET /api/v1/career-path/nodes/

    Browsing the role catalogue is open to any authenticated user; only the
    path-finding endpoints are gated.
    Optional query params: ?category=engineering&level=4
    """

    serializer_class = CareerPathNodeListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # The catalogue is small; return it in one page.

    def get_queryset(self):
        qs = CareerPathNode.objects.filter(is_active=True)

        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)

        level = self.request.query_params.get("level")
        if level:
            qs = qs.filter(level=level)

        return qs.order_by("level", "name")


class CareerPathNodeDetailView(generics.RetrieveAPIView):
    """GET /api/v1/career-path/nodes/<slug>/"""

    serializer_class = CareerPathNodeDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = CareerPathNode.objects.filter(is_active=True)
    lookup_field = "slug"


class FindPathView(APIView):
    """
    POST /api/v1/career-path/find/

    Body: { "from_slug": "...", "to_slug": "...", "max_paths": 3 }
    Paid feature.
    """

    permission_classes = [permissions.IsAuthenticated, HasCareerPath]

    def post(self, request):
        serializer = FindPathInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = CareerPathService.find_paths(
            from_slug=serializer.validated_data["from_slug"],
            to_slug=serializer.validated_data["to_slug"],
            max_paths=serializer.validated_data.get("max_paths", 3),
        )

        # An unknown slug is a client error, not an empty success.
        if result.get("error"):
            return Response(result, status=status.HTTP_404_NOT_FOUND)

        return Response(result)


class FromCurrentView(APIView):
    """
    GET /api/v1/career-path/from-current/

    Roles reachable from the seeker's current_title, which is matched against
    the node catalogue. Paid feature.
    Optional query param: ?max_hops=2
    """

    permission_classes = [IsSeeker, HasCareerPath]

    def get(self, request):
        seeker = request.user.seeker_profile
        current_title = (seeker.current_title or "").strip()

        if not current_title:
            return Response(
                {"error": "Set your current title in your profile first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # First try an exact name match, then fall back to a loose match on the
        # first word so that "Backend Developer at Acme" still resolves.
        node = CareerPathNode.objects.filter(is_active=True, name__iexact=current_title).first()

        if not node:
            node = CareerPathNode.objects.filter(
                is_active=True, name__icontains=current_title.split()[0]
            ).first()

        if not node:
            return Response(
                {
                    "error": (
                        f'Could not match "{current_title}" to any role in the career '
                        f"graph. Browse /career-path/nodes/ to find yours."
                    ),
                    "suggestions": list(
                        CareerPathNode.objects.filter(is_active=True).values("slug", "name")[:10]
                    ),
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            max_hops = int(request.query_params.get("max_hops", 3))
        except (TypeError, ValueError):
            max_hops = 3
        max_hops = max(1, min(max_hops, 5))  # Keep the traversal bounded.

        result = CareerPathService.reachable_from(node.slug, max_hops=max_hops)
        result["matched_from_title"] = current_title
        return Response(result)


class GraphDataView(APIView):
    """
    GET /api/v1/career-path/graph-data/

    The full graph as JSON, for a frontend renderer such as D3 or Sigma.js.
    Not gated: browsing the graph itself is open, only path-finding is paid.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(CareerPathService.get_graph_data())
