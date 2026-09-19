from django.urls import path

from .views import (
    RecruiterAnalyticsView,
    RecruiterDashboardView,
    SeekerDashboardSeenView,
    SeekerDashboardView,
)

app_name = "dashboard"

urlpatterns = [
    path("me/", SeekerDashboardView.as_view(), name="seeker-dashboard"),
    path("me/seen/", SeekerDashboardSeenView.as_view(), name="seeker-dashboard-seen"),
    path("recruiter/", RecruiterDashboardView.as_view(), name="recruiter-dashboard"),
    path("recruiter/analytics/", RecruiterAnalyticsView.as_view(), name="recruiter-analytics"),
]
