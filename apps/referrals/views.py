"""
API views for the referrals app.
"""

from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ReferralReward
from .serializers import (
    ApplyRewardSerializer,
    LeaderboardEntrySerializer,
    MyCodeSerializer,
    MyStatsSerializer,
    ReferralRewardSerializer,
    TrackClickSerializer,
)
from .services import ReferralService


def anonymize_name(full_name: str, email: str) -> str:
    """
    Build a privacy-safe display name for the leaderboard.

    "Priya Kayare" -> "Pri***", and the email prefix is used when the
    user has not set a name.
    """
    name = (full_name or "").strip().split(" ")[0]
    if not name:
        name = (email or "").split("@")[0]
    if not name:
        return "User***"
    return name[:3].capitalize() + "***"


class MyCodeView(APIView):
    """GET /api/v1/referrals/my-code/"""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        code = ReferralService.get_or_create_code(request.user)
        return Response(MyCodeSerializer(code).data)


class MyStatsView(APIView):
    """GET /api/v1/referrals/my-stats/"""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        stats = ReferralService.get_my_stats(request.user)
        return Response(MyStatsSerializer(stats).data)


class MyRewardsView(generics.ListAPIView):
    """GET /api/v1/referrals/my-rewards/"""

    serializer_class = ReferralRewardSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Expire karo list banane se PEHLE, warna user ko ek reward
        # "available" dikhega jo actually expire ho chuka hai.
        # Class body mein nahi rakh sakte: wo import ke waqt ek hi baar
        # chalta hai, jahan na `self` hota hai na koi request.
        ReferralReward.expire_stale(self.request.user)

        return ReferralReward.objects.filter(user=self.request.user).order_by(
            "-granted_at", "-created_at"
        )


class TrackClickView(APIView):
    """
    POST /api/v1/referrals/track-click/
    Body: {"code": "PRIYA-X4F9"}

    Public endpoint: the visitor has not signed up yet when this fires.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = TrackClickSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ReferralService.track_click(serializer.validated_data["code"])
        return Response({"status": "tracked"})


class LeaderboardView(APIView):
    """
    GET /api/v1/referrals/leaderboard/

    Top 20 referrers of the last 30 days, with anonymized names.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        raw = ReferralService.get_leaderboard(limit=20)

        entries = [
            {
                "rank": idx,
                "name": anonymize_name(entry["referrer__full_name"], entry["referrer__email"]),
                "conversion_count": entry["conversion_count"],
                "is_me": entry["referrer__id"] == request.user.id,
            }
            for idx, entry in enumerate(raw, start=1)
        ]

        return Response(
            {
                "leaderboard": LeaderboardEntrySerializer(entries, many=True).data,
                "period": "last_30_days",
            }
        )


class ApplyRewardView(APIView):
    """
    POST /api/v1/referrals/apply-reward/
    Body: {"reward_id": 5}

    Applies a Pro extension reward to the caller's active subscription.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ApplyRewardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ReferralService.apply_pro_extension_reward(
            user=request.user,
            reward_id=serializer.validated_data["reward_id"],
        )
        return Response({"message": "Reward applied successfully."})
