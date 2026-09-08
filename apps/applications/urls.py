from django.urls import path

from .views import (
    ApplyToJobView,
    MyApplicationsView,
    MyApplicationDetailView,
    WithdrawApplicationView,
    ApplicationHistoryView,
    QuotaStatusView,
    JobApplicationsView,
    RecruiterApplicationDetailView,
    UpdateApplicationStatusView,
    UpdateRecruiterNotesView,
)
from apps.resumes.views import ApplicationJdMatchView

# Apply endpoint goes under jobs
apply_patterns = [
    path('<uuid:job_uuid>/apply/', ApplyToJobView.as_view(), name='apply'),
    path('<uuid:job_uuid>/applications/', JobApplicationsView.as_view(), name='job-applications'),
]

# Application management
applications_patterns = [
    # Seeker
    path('me/', MyApplicationsView.as_view(), name='my-list'),
    path('me/quota/', QuotaStatusView.as_view(), name='my-quota'),
    path('me/<int:pk>/', MyApplicationDetailView.as_view(), name='my-detail'),
    path('me/<int:pk>/withdraw/', WithdrawApplicationView.as_view(), name='withdraw'),
    path('me/<int:pk>/history/', ApplicationHistoryView.as_view(), name='my-history'),

    # Recruiter
    path('<int:pk>/', RecruiterApplicationDetailView.as_view(), name='recruiter-detail'),
    path('<int:pk>/status/', UpdateApplicationStatusView.as_view(), name='update-status'),
    path('<int:pk>/notes/', UpdateRecruiterNotesView.as_view(), name='update-notes'),
    path('<int:pk>/history/', ApplicationHistoryView.as_view(), name='recruiter-history'),
    path('<int:pk>/jd-match/', ApplicationJdMatchView.as_view(),name='jd-match'),
]