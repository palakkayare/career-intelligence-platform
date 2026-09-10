import json

from django.contrib import admin
from django.utils.html import format_html

from .models import MatchScore, SavedCandidate


@admin.register(MatchScore)
class MatchScoreAdmin(admin.ModelAdmin):
    list_display = (
        "seeker_email",
        "job_title",
        "overall_score",
        "skills_score",
        "experience_score",
        "computed_at",
    )
    list_filter = (
        "job__company__industry",
        "job__employment_type",
    )
    search_fields = (
        "seeker__user__email",
        "seeker__full_name",
        "job__title",
        "job__company__name",
    )
    raw_id_fields = ("seeker", "job")
    # Scores are computed by the algorithm — editing them by hand
    # would be overwritten on the next recompute anyway
    readonly_fields = (
        "seeker",
        "job",
        "overall_score",
        "skills_score",
        "experience_score",
        "location_score",
        "salary_score",
        "breakdown_pretty",
        "computed_at",
    )
    fields = readonly_fields
    actions = ["recompute_selected"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "seeker__user",
                "job__company",
            )
        )

    @admin.display(description="Seeker")
    def seeker_email(self, obj):
        return obj.seeker.user.email

    @admin.display(description="Job")
    def job_title(self, obj):
        return f"{obj.job.title} @ {obj.job.company.name}"

    @admin.display(description="Breakdown")
    def breakdown_pretty(self, obj):
        """Render the stored JSON breakdown in a readable block."""
        formatted = json.dumps(obj.breakdown, indent=2)
        return format_html('<pre style="white-space: pre-wrap;">{}</pre>', formatted)

    @admin.action(description="Recompute selected match scores")
    def recompute_selected(self, request, queryset):
        from .services import MatchScoreService

        count = 0
        failed = 0
        for ms in queryset:
            try:
                MatchScoreService.compute_and_save(ms.seeker, ms.job)
                count += 1
            except Exception:
                # One bad row should not abort the whole batch
                failed += 1

        msg = f"Recomputed {count} match scores."
        if failed:
            msg += f" {failed} failed."
        self.message_user(request, msg)


@admin.register(SavedCandidate)
class SavedCandidateAdmin(admin.ModelAdmin):
    list_display = ("recruiter", "seeker", "created_at")
    search_fields = (
        "recruiter__user__email",
        "seeker__user__email",
        "recruiter__full_name",
        "seeker__full_name",
    )
    raw_id_fields = ("recruiter", "seeker")
