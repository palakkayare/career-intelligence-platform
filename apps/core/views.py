"""
Cross-cutting views: the admin metrics dashboard.
"""

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """
    GET /api/v1/health/

    Liveness. Answers "is this process alive and serving?" and nothing more,
    so it stays cheap enough for a container healthcheck to poll every few
    seconds. Deliberately does not touch the database: a brief database blip
    should not cause the orchestrator to kill otherwise healthy containers.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok"})


class ReadinessCheckView(APIView):
    """
    GET /api/v1/health/ready/

    Readiness. Answers "can this process actually do work?", which means the
    database and cache have to be reachable. Returns 503 when they are not, so
    a load balancer can take the container out of rotation without killing it.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        from django.core.cache import cache
        from django.db import connection

        checks = {}

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        try:
            cache.set("healthcheck", "ok", 10)
            checks["cache"] = "ok" if cache.get("healthcheck") == "ok" else "error: readback failed"
        except Exception as exc:
            checks["cache"] = f"error: {exc}"

        healthy = all(value == "ok" for value in checks.values())

        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=200 if healthy else 503,
        )


class ClientIpView(APIView):
    """
    GET /api/v1/admin/dashboard/client-ip/

    What the proxies in front of the app actually send, next to the address the
    app settles on. TRUSTED_PROXY_COUNT has to equal the real number of
    proxies, and the only reliable way to know it is to look at a real request
    after every change to the hosting setup. Putting Cloudflare in front adds
    one. Staff only: it shows infrastructure addresses.
    """

    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        from .client_ip import proxy_diagnostics

        return Response(proxy_diagnostics(request))


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
