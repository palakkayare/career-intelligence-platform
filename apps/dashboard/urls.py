from django.urls import path

from .views import SeekerDashboardSeenView, SeekerDashboardView

app_name = "dashboard"

urlpatterns = [
    path("me/", SeekerDashboardView.as_view(), name="seeker-dashboard"),
    path("me/seen/", SeekerDashboardSeenView.as_view(), name="seeker-dashboard-seen"),
]
