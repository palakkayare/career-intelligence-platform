"""
Review endpoints.
"""

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import FlexiblePagination
from apps.recruiters.models import Company
from apps.recruiters.permissions import IsRecruiter
from apps.seekers.permissions import IsSeeker

from .models import CompanyReview
from .serializers import (
    CompanyResponseWriteSerializer,
    CompanyReviewSerializer,
    CompanyReviewWriteSerializer,
    InterviewExperienceSerializer,
    InterviewExperienceWriteSerializer,
    ReportSerializer,
)
from .services import InterviewExperienceService, ModerationService, ResponseService, ReviewService


def get_company(company_id):
    # Company has no public_id field, unlike Job and SeekerProfile - it is
    # addressed by pk everywhere else in the API too.
    return get_object_or_404(Company, pk=company_id, is_deleted=False)


class CompanyReviewListCreateView(APIView):
    """
    GET  /api/v1/reviews/companies/<uuid:public_id>/
    POST /api/v1/reviews/companies/<uuid:public_id>/
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, company_id):
        company = get_company(company_id)
        reviews = ReviewService.published_for(company)

        paginator = FlexiblePagination()
        page = paginator.paginate_queryset(reviews, request)

        return paginator.get_paginated_response(
            CompanyReviewSerializer(
                page,
                many=True,
                context={"request": request},
            ).data,
        )

    def post(self, request, company_id):
        # Only seekers review companies. A recruiter reviewing a rival is
        # not the signal this feature is for.
        if not request.user.is_seeker:
            return Response(
                {"detail": "Only job seekers can review companies."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = get_company(company_id)
        serializer = CompanyReviewWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review = ReviewService.create(
            request.user,
            company,
            serializer.validated_data,
        )

        return Response(
            CompanyReviewSerializer(review, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class CompanyReviewSummaryView(APIView):
    """GET /api/v1/reviews/companies/<uuid:public_id>/summary/"""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, company_id):
        company = get_company(company_id)

        return Response(
            {
                "company": company.name,
                "reviews": ReviewService.summary(company),
                "interviews": InterviewExperienceService.summary(company),
            }
        )


class ReviewDetailView(APIView):
    """
    PATCH  /api/v1/reviews/<int:pk>/  - edit, within the window
    DELETE /api/v1/reviews/<int:pk>/  - withdraw
    """

    permission_classes = [IsSeeker]

    def get_object(self, pk):
        return get_object_or_404(CompanyReview, pk=pk, is_deleted=False)

    def patch(self, request, pk):
        review = self.get_object(pk)
        serializer = CompanyReviewWriteSerializer(
            review,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        ReviewService.update(review, request.user, serializer.validated_data)

        return Response(
            CompanyReviewSerializer(review, context={"request": request}).data,
        )

    def delete(self, request, pk):
        ReviewService.delete(self.get_object(pk), request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReviewHelpfulView(APIView):
    """POST /api/v1/reviews/<int:pk>/helpful/"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        review = get_object_or_404(CompanyReview, pk=pk, is_deleted=False)
        review, created = ReviewService.mark_helpful(review, request.user)

        return Response(
            {"helpful_count": review.helpful_count},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ReviewReportView(APIView):
    """POST /api/v1/reviews/<int:pk>/report/"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        review = get_object_or_404(CompanyReview, pk=pk, is_deleted=False)
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ModerationService.report(
            review,
            request.user,
            reason=serializer.validated_data["reason"],
            detail=serializer.validated_data.get("detail", ""),
        )

        # The response says nothing about whether the review was hidden.
        # Telling a reporter how close they are to the threshold is an
        # invitation to organise the remaining reports.
        return Response(
            {"detail": "Thank you. A moderator will look at this."},
            status=status.HTTP_201_CREATED,
        )


class CompanyResponseView(APIView):
    """POST /api/v1/reviews/<int:pk>/respond/"""

    permission_classes = [IsRecruiter]

    def post(self, request, pk):
        review = get_object_or_404(CompanyReview, pk=pk, is_deleted=False)
        serializer = CompanyResponseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ResponseService.respond(
            review,
            request.user.recruiter_profile,
            serializer.validated_data["response"],
        )

        return Response(
            CompanyReviewSerializer(review, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class InterviewExperienceListCreateView(APIView):
    """
    GET  /api/v1/reviews/companies/<uuid:public_id>/interviews/
    POST /api/v1/reviews/companies/<uuid:public_id>/interviews/
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, company_id):
        company = get_company(company_id)
        experiences = InterviewExperienceService.published_for(company)

        paginator = FlexiblePagination()
        page = paginator.paginate_queryset(experiences, request)

        return paginator.get_paginated_response(
            InterviewExperienceSerializer(
                page,
                many=True,
                context={"request": request},
            ).data,
        )

    def post(self, request, company_id):
        if not request.user.is_seeker:
            return Response(
                {"detail": "Only job seekers can share interview experiences."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = get_company(company_id)
        serializer = InterviewExperienceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        experience = InterviewExperienceService.create(
            request.user,
            company,
            serializer.validated_data,
        )

        return Response(
            InterviewExperienceSerializer(
                experience,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ModerationQueueView(APIView):
    """
    GET /api/v1/reviews/moderation/queue/

    Admin only. Reviews hidden by reports, waiting on a decision.
    """

    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        queue = ModerationService.queue()

        return Response(
            {
                "count": queue.count(),
                "reviews": [
                    {
                        "id": review.id,
                        "company": review.company.name,
                        "headline": review.headline,
                        "pros": review.pros,
                        "cons": review.cons,
                        "report_count": review.report_count,
                        "reasons": list(
                            review.reports.values_list("reason", flat=True),
                        ),
                        "created_at": review.created_at,
                    }
                    for review in queue
                ],
            }
        )


class ModerationDecisionView(APIView):
    """
    POST /api/v1/reviews/moderation/<int:pk>/<str:decision>/

    decision is 'restore' or 'remove'.
    """

    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk, decision):
        review = get_object_or_404(CompanyReview, pk=pk)
        notes = request.data.get("notes", "")

        if decision == "restore":
            ModerationService.restore(review, notes)
        elif decision == "remove":
            ModerationService.remove(review, notes)
        else:
            return Response(
                {"detail": "Decision must be 'restore' or 'remove'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"id": review.id, "status": review.status})
