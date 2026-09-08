"""
Serializers for the referrals API.
"""

from django.conf import settings
from rest_framework import serializers

from .models import ReferralCode, ReferralReward


class MyCodeSerializer(serializers.ModelSerializer):
    """The caller's own referral code plus a ready-to-share URL."""

    share_url = serializers.SerializerMethodField()

    class Meta:
        model = ReferralCode
        fields = ('code', 'share_url', 'click_count', 'signup_count', 'paid_count')
        read_only_fields = fields

    def get_share_url(self, obj):
        # The path must match the frontend router. The signup screen is served
        # at /register (App.jsx), so /signup lands on a 404 and the referral is
        # lost before it is ever captured.
        return f"{settings.FRONTEND_URL}/register?ref={obj.code}"


class MyStatsSerializer(serializers.Serializer):
    """Funnel metrics for the caller. Built from a plain dict, not a model."""

    code = serializers.CharField()
    share_url = serializers.CharField()
    click_count = serializers.IntegerField()
    signup_count = serializers.IntegerField()
    paid_count = serializers.IntegerField()
    conversion_rate = serializers.FloatField()


class ReferralRewardSerializer(serializers.ModelSerializer):
    # is_usable is a model method; DRF calls it automatically
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = ReferralReward
        fields = (
            'id', 'kind', 'value',
            'status', 'granted_at', 'used_at', 'expires_at',
            'is_usable',
        )
        read_only_fields = fields


class TrackClickSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)


class LeaderboardEntrySerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    name = serializers.CharField()
    conversion_count = serializers.IntegerField()
    is_me = serializers.BooleanField()


class ApplyRewardSerializer(serializers.Serializer):
    reward_id = serializers.IntegerField()