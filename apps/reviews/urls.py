from django.urls import path

from .views import (
    CompanyResponseView,
    CompanyReviewListCreateView,
    CompanyReviewSummaryView,
    InterviewExperienceListCreateView,
    ModerationDecisionView,
    ModerationQueueView,
    ReviewDetailView,
    ReviewHelpfulView,
    ReviewReportView,
)

reviews_patterns = [
    path(
        "companies/<int:company_id>/",
        CompanyReviewListCreateView.as_view(),
        name="company-reviews",
    ),
    path(
        "companies/<int:company_id>/summary/",
        CompanyReviewSummaryView.as_view(),
        name="company-review-summary",
    ),
    path(
        "companies/<int:company_id>/interviews/",
        InterviewExperienceListCreateView.as_view(),
        name="company-interviews",
    ),
    path("<int:pk>/", ReviewDetailView.as_view(), name="review-detail"),
    path("<int:pk>/helpful/", ReviewHelpfulView.as_view(), name="review-helpful"),
    path("<int:pk>/report/", ReviewReportView.as_view(), name="review-report"),
    path("<int:pk>/respond/", CompanyResponseView.as_view(), name="review-respond"),
    path("moderation/queue/", ModerationQueueView.as_view(), name="moderation-queue"),
    path(
        "moderation/<int:pk>/<str:decision>/",
        ModerationDecisionView.as_view(),
        name="moderation-decision",
    ),
]
