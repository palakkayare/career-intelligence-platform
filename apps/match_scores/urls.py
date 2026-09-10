from django.urls import path

from .views import (
    JobMatchScoreView,
    JobRecommendedCandidatesView,
    RecommendedJobsView,
    SavedCandidateDetailView,
    SavedCandidatesView,
)

# Score endpoints, nested under /jobs/<uuid>/
job_match_patterns = [
    path("<uuid:public_id>/match-score/", JobMatchScoreView.as_view(), name="match-score"),
    path(
        "<uuid:public_id>/recommended-candidates/",
        JobRecommendedCandidatesView.as_view(),
        name="recommended-candidates",
    ),
]

# Match-related endpoints, under /match/
match_patterns = [
    path("recommended-jobs/", RecommendedJobsView.as_view(), name="recommended-jobs"),
    path("saved-candidates/", SavedCandidatesView.as_view(), name="saved-candidates"),
    path(
        "saved-candidates/<int:pk>/",
        SavedCandidateDetailView.as_view(),
        name="saved-candidate-detail",
    ),
]
