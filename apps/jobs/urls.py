from django.urls import path


from .views import (
    SaveJobView,
    UnsaveJobView,
    SavedJobListView,
    JobCategoryListView, TagListView,
    PublicJobListView, JobDetailView, IncrementJobViewView,
    MyJobListCreateView, JobUpdateDestroyView,
    SubmitJobView, CloseJobView, DuplicateJobView, BackToDraftView,
    AdminPendingJobsView, AdminApproveJobView, AdminRejectJobView,
    JobSearchView,
    SavedSearchListCreateView, SavedSearchDestroyView, ExecuteSavedSearchView,
    SearchHistoryView,
)

# Categories & Tags
taxonomy_patterns = [
    path('job-categories/', JobCategoryListView.as_view(), name='categories'),
    path('job-tags/', TagListView.as_view(), name='tags'),
]

# Public + Recruiter-side jobs
jobs_patterns = [
    # Search
    path('search/', JobSearchView.as_view(), name='search'),

    # Saved jobs (bookmarks)
    path('saved/', SavedJobListView.as_view(), name='saved-jobs'),

    # Saved searches
    path('saved-searches/', SavedSearchListCreateView.as_view(), name='saved-list'),
    path('saved-searches/<int:pk>/', SavedSearchDestroyView.as_view(), name='saved-delete'),
    path('saved-searches/<int:pk>/execute/', ExecuteSavedSearchView.as_view(), name='saved-execute'),

    # History
    path('search-history/', SearchHistoryView.as_view(), name='history'),

    # Job CRUD (existing)
    path('', PublicJobListView.as_view(), name='public-list'),
    path('my/', MyJobListCreateView.as_view(), name='my-jobs'),
    path('<uuid:public_id>/', JobDetailView.as_view(), name='detail'),
    path('<uuid:public_id>/edit/', JobUpdateDestroyView.as_view(), name='edit'),
    path('<uuid:public_id>/view/', IncrementJobViewView.as_view(), name='view'),
    path('<uuid:job_uuid>/save/', SaveJobView.as_view(), name='save'),
    path('<uuid:job_uuid>/unsave/', UnsaveJobView.as_view(), name='unsave'),
    path('<uuid:public_id>/submit/', SubmitJobView.as_view(), name='submit'),
    path('<uuid:public_id>/close/', CloseJobView.as_view(), name='close'),
    path('<uuid:public_id>/duplicate/', DuplicateJobView.as_view(), name='duplicate'),
    path('<uuid:public_id>/back-to-draft/', BackToDraftView.as_view(), name='back-to-draft'),
]

# Admin
admin_jobs_patterns = [
    path('pending/', AdminPendingJobsView.as_view(), name='pending'),
    path('<uuid:public_id>/approve/', AdminApproveJobView.as_view(), name='approve'),
    path('<uuid:public_id>/reject/', AdminRejectJobView.as_view(), name='reject'),
    
]