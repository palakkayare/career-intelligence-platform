from django.urls import path

from .views import (
    ActivityMetricsView,
    AdminDashboardView,
    ClientIpView,
    HealthCheckView,
    ReadinessCheckView,
    RevenueMetricsView,
)

admin_dashboard_patterns = [
    path("", AdminDashboardView.as_view(), name="dashboard"),
    path("revenue/", RevenueMetricsView.as_view(), name="dashboard-revenue"),
    path("activity/", ActivityMetricsView.as_view(), name="dashboard-activity"),
    path("client-ip/", ClientIpView.as_view(), name="dashboard-client-ip"),
]

health_patterns = [
    path("", HealthCheckView.as_view(), name="health"),
    path("ready/", ReadinessCheckView.as_view(), name="health-ready"),
]
