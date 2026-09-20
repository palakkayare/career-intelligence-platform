import logging

from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.permissions import HasFeature
from apps.recruiters.permissions import IsRecruiter
from apps.seekers.permissions import IsSeeker

from .serializers import (
    DashboardResponseSerializer,
    DashboardSeenSerializer,
    RecruiterAnalyticsSerializer,
    RecruiterDashboardSerializer,
)
from .services import CACHE_SECONDS, build_dashboard, cache_key, mark_seen

logger = logging.getLogger(__name__)


class SeekerDashboardView(APIView):
    """
    GET /api/v1/dashboard/me/

    Everything the seeker home screen draws, in one response. Sections that
    fail are returned as null and listed in `errors`; the request still
    answers 200.
    """

    permission_classes = [IsSeeker]

    @extend_schema(responses={200: DashboardResponseSerializer}, tags=["dashboard"])
    def get(self, request):
        key = cache_key(request.user.pk)
        # The cache saves work; it is not allowed to cost the whole screen.
        # If it is unreachable the dashboard is simply built every time.
        try:
            data = cache.get(key)
        except Exception:  # noqa: BLE001 - any cache backend failure
            logger.warning("Dashboard cache unavailable on read")
            data = None

        if data is None:
            profile = request.user.seeker_profile
            data = build_dashboard(request.user, profile, request=request)
            # A response with a broken section is not cached, so the next
            # request gets a fresh attempt instead of a minute of the error.
            if not data["errors"]:
                try:
                    cache.set(key, data, CACHE_SECONDS)
                except Exception:  # noqa: BLE001
                    logger.warning("Dashboard cache unavailable on write")

        response = Response(data)
        # Never "private, max-age": the browser keys its cache on the URL, not
        # on who asked, so after a logout and a login on the same machine the
        # next person was served the previous person's dashboard. The
        # server-side cache above is keyed per user and does the real saving.
        response["Cache-Control"] = "no-store"
        return response


class SeekerDashboardSeenView(APIView):
    """
    POST /api/v1/dashboard/me/seen/

    Records that the seeker has looked at the dashboard. Separate from the
    GET on purpose: reading must not change what "new since last visit"
    means while the page is still open. Sent with navigator.sendBeacon when
    the page closes.
    """

    permission_classes = [IsSeeker]

    @extend_schema(request=None, responses={200: DashboardSeenSerializer}, tags=["dashboard"])
    def post(self, request):
        when = mark_seen(request.user.seeker_profile)
        return Response({"last_seen_at": when})


class RecruiterDashboardView(APIView):
    """
    GET /api/v1/dashboard/recruiter/

    Everything the recruiter home screen draws, counted in the database
    rather than assembled from per-job pages on the client.
    """

    permission_classes = [IsRecruiter]

    @extend_schema(responses={200: RecruiterDashboardSerializer}, tags=["dashboard"])
    def get(self, request):
        from .recruiter_services import build_recruiter_dashboard

        profile = request.user.recruiter_profile
        response = Response(build_recruiter_dashboard(profile))
        # Never "private, max-age": the browser keys its cache on the URL, not
        # on who asked, so after a logout and a login on the same machine the
        # next person was served the previous person's dashboard. The
        # server-side cache above is keyed per user and does the real saving.
        response["Cache-Control"] = "no-store"
        return response


HasAnalytics = HasFeature.create("analytics_dashboard")


class RecruiterAnalyticsView(APIView):
    """
    GET /api/v1/dashboard/recruiter/analytics/

    Hiring analytics, counted in the database. Business plan only, the same
    gate the rest of the analytics feature uses.
    """

    permission_classes = [IsRecruiter, HasAnalytics]

    @extend_schema(responses={200: RecruiterAnalyticsSerializer}, tags=["dashboard"])
    def get(self, request):
        from .recruiter_services import build_recruiter_analytics

        response = Response(build_recruiter_analytics(request.user.recruiter_profile))
        response["Cache-Control"] = "no-store"  # per-user payload; see above
        return response
