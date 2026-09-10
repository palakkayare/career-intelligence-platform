from django.contrib import admin

from .models import Referral, ReferralCode, ReferralReward


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "user",
        "click_count",
        "signup_count",
        "paid_count",
        "is_active",
    )
    search_fields = ("code", "user__email")
    raw_id_fields = ("user",)


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = (
        "referrer",
        "referee",
        "status",
        "is_flagged",
        "signup_at",
        "converted_at",
        "converted_amount_inr",
    )
    list_filter = ("status", "is_flagged")
    search_fields = ("referrer__email", "referee__email")
    raw_id_fields = ("referrer", "referee", "code_used")
    actions = ["mark_flagged", "unflag"]

    @admin.action(description="Flag selected referrals as suspicious")
    def mark_flagged(self, request, queryset):
        count = queryset.update(is_flagged=True, status=Referral.Status.FLAGGED)
        self.message_user(request, f"Flagged {count} referrals.")

    @admin.action(description="Remove the flag from selected referrals")
    def unflag(self, request, queryset):
        count = queryset.update(is_flagged=False, flag_reason="")
        self.message_user(request, f"Unflagged {count} referrals.")


@admin.register(ReferralReward)
class ReferralRewardAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "status", "granted_at", "used_at", "expires_at")
    list_filter = ("kind", "status")
    search_fields = ("user__email",)
    raw_id_fields = ("referral", "user")
