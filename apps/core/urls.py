from django.urls import path

from .views import (
    ActivityMetricsView,
    AdminDashboardView,
    HealthCheckView,
    ReadinessCheckView,
    RevenueMetricsView,
)

admin_dashboard_patterns = [
    path('', AdminDashboardView.as_view(), name='dashboard'),
    path('revenue/', RevenueMetricsView.as_view(), name='dashboard-revenue'),
    path('activity/', ActivityMetricsView.as_view(), name='dashboard-activity'),
]

health_patterns = [
    path('', HealthCheckView.as_view(), name='health'),
    path('ready/', ReadinessCheckView.as_view(), name='health-ready'),
]