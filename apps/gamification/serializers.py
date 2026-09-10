from rest_framework import serializers

from .models import Badge, PerkRedemption, PointsLedger, WeeklyGoal


class BadgeSerializer(serializers.ModelSerializer):
    earned = serializers.SerializerMethodField()
    earned_at = serializers.SerializerMethodField()

    class Meta:
        model = Badge
        fields = (
            "id",
            "code",
            "name",
            "description",
            "category",
            "points",
            "icon",
            "earned",
            "earned_at",
        )

    def get_earned(self, obj):
        return obj.code in self.context.get("earned_codes", set())

    def get_earned_at(self, obj):
        return self.context.get("earned_dates", {}).get(obj.code)


class PointsLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointsLedger
        fields = ("id", "delta", "reason", "detail", "created_at")


class SetGoalSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=WeeklyGoal.Kind.choices)
    target = serializers.IntegerField(min_value=1, max_value=50)


class RedeemPerkSerializer(serializers.Serializer):
    perk = serializers.ChoiceField(choices=PerkRedemption.Perk.choices)
