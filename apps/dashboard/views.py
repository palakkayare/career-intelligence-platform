from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.seekers.permissions import IsSeeker

from .serializers import DashboardResponseSerializer, DashboardSeenSerializer
from .services import CACHE_SECONDS, build_dashboard, cache_key, mark_seen


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
        data = cache.get(key)
        if data is None:
            profile = request.user.seeker_profile
            data = build_dashboard(request.user, profile, request=request)
            # A response with a broken section is not cached, so the next
            # request gets a fresh attempt instead of a minute of the error.
            if not data["errors"]:
                cache.set(key, data, CACHE_SECONDS)

        response = Response(data)
        response["Cache-Control"] = "private, max-age=30"
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
