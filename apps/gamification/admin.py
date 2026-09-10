from django.contrib import admin

from .models import (
    ApplicationStreak,
    Badge,
    EarnedBadge,
    PerkRedemption,
    PointsLedger,
    WeeklyGoal,
)


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'threshold', 'points',
                    'sort_order', 'is_active')
    list_filter = ('category', 'is_active')
    list_editable = ('points', 'sort_order', 'is_active')
    search_fields = ('code', 'name')


@admin.register(EarnedBadge)
class EarnedBadgeAdmin(admin.ModelAdmin):
    list_display = ('user', 'badge', 'earned_at')
    list_filter = ('badge__category',)
    search_fields = ('user__email', 'badge__code')
    raw_id_fields = ('user', 'badge')

    def has_add_permission(self, request):
        return False


@admin.register(ApplicationStreak)
class ApplicationStreakAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_weeks', 'longest_weeks',
                    'last_active_week')
    search_fields = ('user__email',)
    raw_id_fields = ('user',)


@admin.register(WeeklyGoal)
class WeeklyGoalAdmin(admin.ModelAdmin):
    list_display = ('user', 'kind', 'target', 'week_start', 'achieved_at')
    list_filter = ('kind', 'week_start')
    search_fields = ('user__email',)
    raw_id_fields = ('user',)


@admin.register(PointsLedger)
class PointsLedgerAdmin(admin.ModelAdmin):
    list_display = ('user', 'delta', 'reason', 'detail', 'created_at')
    list_filter = ('reason', 'created_at')
    search_fields = ('user__email', 'detail')
    raw_id_fields = ('user',)
    date_hierarchy = 'created_at'

    # The ledger is the audit trail for points. Editing an entry would make
    # a balance impossible to explain.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PerkRedemption)
class PerkRedemptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'perk', 'points_spent', 'expires_at')
    list_filter = ('perk',)
    search_fields = ('user__email',)
    raw_id_fields = ('user',)

    def has_add_permission(self, request):
        return False
