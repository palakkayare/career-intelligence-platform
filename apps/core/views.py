"""
Cross-cutting views: the admin metrics dashboard.
"""
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


class AdminDashboardView(APIView):
    """
    GET /api/v1/admin/dashboard/

    Blueprint Feature 10: "Subscription and revenue dashboard: MRR, churn
    rate, active plans" and "Platform health metrics: DAU, MAU, applications
    per day".
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        from .metrics import dashboard_snapshot

        return Response(dashboard_snapshot())


class RevenueMetricsView(APIView):
    """GET /api/v1/admin/dashboard/revenue/"""
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        from .metrics import RevenueMetrics

        return Response(RevenueMetrics.summary())


class ActivityMetricsView(APIView):
    """GET /api/v1/admin/dashboard/activity/"""
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        from .metrics import ActivityMetrics

        return Response(ActivityMetrics.summary())