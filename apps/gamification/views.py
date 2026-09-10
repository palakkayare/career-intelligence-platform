"""
Gamification endpoints.
"""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.seekers.permissions import IsSeeker

from .models import Badge, EarnedBadge
from .serializers import (
    BadgeSerializer,
    PointsLedgerSerializer,
    RedeemPerkSerializer,
    SetGoalSerializer,
)
from .services import (
    BadgeService,
    GoalService,
    PerkService,
    PointsService,
    StreakService,
)


class MyProgressView(APIView):
    """
    GET /api/v1/gamification/me/

    Everything at once: badges, streak, goals, points. One call because a
    dashboard that needs four round trips renders in pieces.
    """
    permission_classes = [IsSeeker]

    def get(self, request):
        user = request.user

        # Checked on read rather than on write - see signals.py
        BadgeService.check_all(user)

        earned = EarnedBadge.objects.filter(user=user).select_related('badge')
        earned_codes = {e.badge.code for e in earned}
        earned_dates = {e.badge.code: e.earned_at for e in earned}

        badges = Badge.objects.filter(is_active=True)

        return Response({
            'points': PointsService.balance(user),
            'badges': BadgeSerializer(
                badges, many=True,
                context={'earned_codes': earned_codes,
                         'earned_dates': earned_dates},
            ).data,
            'badges_earned': len(earned_codes),
            'badges_total': badges.count(),
            'streak': StreakService.current(user),
            'goals': GoalService.progress(user),
            'perks': PerkService.available(user),
        })


class PointsHistoryView(APIView):
    """GET /api/v1/gamification/points/"""
    permission_classes = [IsSeeker]

    def get(self, request):
        return Response({
            'balance': PointsService.balance(request.user),
            'history': PointsLedgerSerializer(
                PointsService.history(request.user), many=True,
            ).data,
        })


class WeeklyGoalView(APIView):
    """
    GET  /api/v1/gamification/goals/  - this week's goals and progress
    POST /api/v1/gamification/goals/  - set or update one
    """
    permission_classes = [IsSeeker]

    def get(self, request):
        return Response({'goals': GoalService.progress(request.user)})

    def post(self, request):
        serializer = SetGoalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        GoalService.set_goal(
            request.user,
            kind=serializer.validated_data['kind'],
            target=serializer.validated_data['target'],
        )
        # A goal set below what the person has already done this week counts
        # immediately, which is correct - they did the work.
        GoalService.check_achieved(request.user)

        return Response(
            {'goals': GoalService.progress(request.user)},
            status=status.HTTP_201_CREATED,
        )


class RedeemPerkView(APIView):
    """POST /api/v1/gamification/perks/redeem/"""
    permission_classes = [IsSeeker]

    def post(self, request):
        serializer = RedeemPerkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        redemption = PerkService.redeem(
            request.user, serializer.validated_data['perk'],
        )

        return Response({
            'perk': redemption.perk,
            'points_spent': redemption.points_spent,
            'expires_at': redemption.expires_at,
            'balance': PointsService.balance(request.user),
        }, status=status.HTTP_201_CREATED)
