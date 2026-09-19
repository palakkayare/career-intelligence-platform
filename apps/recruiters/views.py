from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Company, RecruiterProfile
from .permissions import IsCompanyAdminOrReadOnly, IsRecruiter
from .serializers import (
    CompanyDetailSerializer,
    CompanyJoinInputSerializer,
    CompanyJoinRequestSerializer,
    CompanyJoinResultSerializer,
    CompanyListSerializer,
    CompanyLogoSerializer,
    RecruiterProfileSerializer,
    RecruiterProfileUpdateSerializer,
)


class CompanyListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/companies/  ← Anyone authenticated
    POST /api/v1/companies/  ← Recruiters only
    """

    def get_serializer_class(self):
        return CompanyListSerializer if self.request.method == "GET" else CompanyDetailSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsRecruiter()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = Company.objects.select_related("industry").filter(is_deleted=False)

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q)

        industry_id = self.request.query_params.get("industry")
        if industry_id:
            qs = qs.filter(industry_id=industry_id)

        verified_only = self.request.query_params.get("verified") == "true"
        if verified_only:
            qs = qs.filter(is_verified=True)

        return qs.order_by("-is_verified", "name")

    def perform_create(self, serializer):
        # Recruiter must NOT already be in a company (Phase 1 rule)
        recruiter = self.request.user.recruiter_profile
        if recruiter.company_id:
            raise serializers.ValidationError(
                {"detail": "You are already part of a company. Leave it first."}
            )

        company = serializer.save(created_by=self.request.user)

        # Creator becomes company admin
        recruiter.company = company
        recruiter.is_company_admin = True
        recruiter.save(update_fields=["company", "is_company_admin"])


class CompanyDetailView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/companies/<id>/  ← Anyone authenticated
    PATCH /api/v1/companies/<id>/  ← Company admin only
    """

    queryset = Company.objects.select_related("industry").filter(is_deleted=False)
    serializer_class = CompanyDetailSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]


class CompanyLogoView(APIView):
    """POST /api/v1/companies/<id>/logo/"""

    permission_classes = [IsRecruiter, IsCompanyAdminOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        company = get_object_or_404(Company, pk=pk, is_deleted=False)
        self.check_object_permissions(request, company)

        serializer = CompanyLogoSerializer(company, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "logo": company.logo.url if company.logo else None,
            }
        )


class CompanyTeamView(generics.ListAPIView):
    """GET /api/v1/companies/<id>/team/ ← List recruiters in this company."""

    serializer_class = RecruiterProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        company_id = self.kwargs["pk"]
        return (
            RecruiterProfile.objects.select_related("user", "company")
            .filter(company_id=company_id, is_deleted=False)
            .order_by("-is_company_admin", "full_name")
        )

    def get_serializer_context(self):
        return {"request": self.request}


class CompanyJoinView(APIView):
    """
    POST /api/v1/companies/<id>/join/

    Asks to join. An admin of that company approves, except when the company
    has no members yet or the recruiter's email domain matches the company's
    website - see CompanyJoinService.
    """

    permission_classes = [IsRecruiter]

    @extend_schema(
        request=CompanyJoinInputSerializer,
        responses={200: CompanyJoinResultSerializer, 202: CompanyJoinResultSerializer},
        tags=["companies"],
    )
    def post(self, request, pk):
        company = get_object_or_404(Company, pk=pk, is_deleted=False)
        recruiter = request.user.recruiter_profile

        from .services import CompanyJoinService

        join_request, joined = CompanyJoinService.request_to_join(
            recruiter, company, message=request.data.get("message", "")
        )

        if joined:
            return Response(
                {
                    "status": "joined",
                    "message": f"Joined {company.name} successfully.",
                    "company": CompanyListSerializer(company).data,
                }
            )
        return Response(
            {
                "status": "pending",
                "message": (
                    f"Your request to join {company.name} is waiting for " "one of their admins."
                ),
                "request_id": join_request.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class CompanyJoinRequestListView(APIView):
    """
    GET /api/v1/companies/join-requests/

    Pending requests for the admin's own company, plus the recruiter's own
    request while it waits.
    """

    permission_classes = [IsRecruiter]

    @extend_schema(responses={200: CompanyJoinRequestSerializer(many=True)}, tags=["companies"])
    def get(self, request):
        from .models import CompanyJoinRequest

        recruiter = request.user.recruiter_profile
        qs = CompanyJoinRequest.objects.filter(status=CompanyJoinRequest.Status.PENDING)
        if recruiter.company_id and recruiter.is_company_admin:
            qs = qs.filter(company_id=recruiter.company_id)
        else:
            qs = qs.filter(recruiter=recruiter)
        qs = qs.select_related("recruiter", "recruiter__user")
        return Response(CompanyJoinRequestSerializer(qs, many=True).data)


class CompanyJoinRequestDecideView(APIView):
    """POST /api/v1/companies/join-requests/<id>/<approve|reject>/"""

    permission_classes = [IsRecruiter]

    @extend_schema(request=None, responses={200: CompanyJoinRequestSerializer}, tags=["companies"])
    def post(self, request, pk, action):
        from .models import CompanyJoinRequest
        from .services import CompanyJoinService

        join_request = get_object_or_404(CompanyJoinRequest, pk=pk)
        decided = CompanyJoinService.decide(
            join_request, request.user.recruiter_profile, approve=(action == "approve")
        )
        return Response(CompanyJoinRequestSerializer(decided).data)


class CompanyLeaveView(APIView):
    """POST /api/v1/companies/<id>/leave/"""

    permission_classes = [IsRecruiter]

    def post(self, request, pk):
        recruiter = request.user.recruiter_profile

        if recruiter.company_id != int(pk):
            return Response(
                {"error": "You are not part of this company."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If admin, ensure another admin exists OR transfer/dissolve
        if recruiter.is_company_admin:
            other_admins = (
                RecruiterProfile.objects.filter(
                    company_id=pk,
                    is_company_admin=True,
                    is_deleted=False,
                )
                .exclude(id=recruiter.id)
                .count()
            )

            if other_admins == 0:
                return Response(
                    {
                        "error": (
                            "You are the only admin. "
                            "Promote another member first or contact support."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        recruiter.company = None
        recruiter.is_company_admin = False
        recruiter.save(update_fields=["company", "is_company_admin"])

        return Response({"message": "Left the company."})


class CompanyMemberPromoteView(APIView):
    """
    POST /api/v1/companies/<pk>/members/<recruiter_id>/promote/
    Company admin promotes a member to admin.
    """

    permission_classes = [IsRecruiter]

    def post(self, request, pk, recruiter_id):
        actor = request.user.recruiter_profile

        if actor.company_id != int(pk) or not actor.is_company_admin:
            return Response(
                {"error": "Only company admins can promote members."},
                status=status.HTTP_403_FORBIDDEN,
            )

        target = get_object_or_404(
            RecruiterProfile,
            id=recruiter_id,
            company_id=pk,
            is_deleted=False,
        )
        target.is_company_admin = True
        target.save(update_fields=["is_company_admin"])

        return Response({"message": f"{target.full_name} promoted to admin."})


class CompanyMemberRemoveView(APIView):
    """
    POST /api/v1/companies/<pk>/members/<recruiter_id>/remove/
    Company admin removes a member from the company.
    """

    permission_classes = [IsRecruiter]

    def post(self, request, pk, recruiter_id):
        actor = request.user.recruiter_profile

        if actor.company_id != int(pk) or not actor.is_company_admin:
            return Response(
                {"error": "Only company admins can remove members."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if actor.id == int(recruiter_id):
            return Response(
                {"error": "Use /leave/ to remove yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target = get_object_or_404(
            RecruiterProfile,
            id=recruiter_id,
            company_id=pk,
            is_deleted=False,
        )
        target.company = None
        target.is_company_admin = False
        target.save(update_fields=["company", "is_company_admin"])

        return Response({"message": "Member removed."})


class MyRecruiterProfileView(generics.RetrieveUpdateAPIView):
    """GET, PATCH /api/v1/recruiters/me/"""

    permission_classes = [IsRecruiter]

    def get_object(self):
        return self.request.user.recruiter_profile

    def get_serializer_class(self):
        if self.request.method == "GET":
            return RecruiterProfileSerializer
        return RecruiterProfileUpdateSerializer

    def get_serializer_context(self):
        return {"request": self.request}


class PublicRecruiterProfileView(generics.RetrieveAPIView):
    """GET /api/v1/recruiters/<public_id>/"""

    serializer_class = RecruiterProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "user__public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        return RecruiterProfile.objects.select_related("user", "company")

    def get_serializer_context(self):
        return {"request": self.request}
