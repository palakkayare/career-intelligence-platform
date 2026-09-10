from django.contrib import admin
from django.utils import timezone

from apps.core.admin import SoftDeleteAdminMixin

from .models import CandidateView, Company, RecruiterCredits, RecruiterProfile


@admin.register(Company)
class CompanyAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "industry", "size", "is_verified", "created_at")
    list_filter = ("is_verified", "size", "industry", "is_deleted")
    search_fields = ("name", "website")
    raw_id_fields = ("industry", "created_by")
    readonly_fields = ("verified_at", "slug")
    actions = ["verify_companies"]

    @admin.action(description="Mark selected companies as verified")
    def verify_companies(self, request, queryset):
        # Single UPDATE statement — no per-row save() needed here.
        count = queryset.filter(is_verified=False).update(
            is_verified=True,
            verified_at=timezone.now(),
        )
        self.message_user(request, f"Verified {count} company(ies).")


@admin.register(RecruiterProfile)
class RecruiterProfileAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "user_email",
        "company",
        "position",
        "is_company_admin",
        "contact_visibility",
    )
    list_filter = ("is_company_admin", "contact_visibility")
    search_fields = ("full_name", "user__email", "company__name")
    raw_id_fields = ("user", "company")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "company")

    @admin.display(description="Email")
    def user_email(self, obj):
        return obj.user.email


@admin.register(RecruiterCredits)
class RecruiterCreditsAdmin(admin.ModelAdmin):
    list_display = (
        "recruiter",
        "monthly_reveal_limit",
        "reveals_used_this_month",
        "remaining",
        "cycle_starts_on",
        "cycle_ends_on",
    )
    search_fields = ("recruiter__user__email", "recruiter__full_name")
    raw_id_fields = ("recruiter",)
    readonly_fields = ("cycle_starts_on",)
    actions = ["reset_cycles"]

    @admin.action(description="Reset cycle for selected recruiters")
    def reset_cycles(self, request, queryset):
        count = queryset.count()
        for credits in queryset:
            credits.reset_cycle()
        self.message_user(request, f"Reset {count} credit cycles.")


@admin.register(CandidateView)
class CandidateViewAdmin(admin.ModelAdmin):
    list_display = (
        "recruiter",
        "seeker",
        "view_kind",
        "contact_revealed",
        "revealed_at",
        "created_at",
    )
    list_filter = ("view_kind", "contact_revealed")
    search_fields = ("recruiter__user__email", "seeker__user__email")
    raw_id_fields = ("recruiter", "seeker", "target_job")
    readonly_fields = (
        "view_kind",
        "contact_revealed",
        "revealed_at",
        "created_at",
    )
