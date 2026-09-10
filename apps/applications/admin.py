from django.contrib import admin

from .models import Application, ApplicationStatusHistory


class StatusHistoryInline(admin.TabularInline):
    """Show the status history timeline inline on the Application page."""

    model = ApplicationStatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "notes", "created_at")
    ordering = ("created_at",)

    def has_add_permission(self, request, obj=None):
        # History rows are written by the state machine, never by hand.
        return False


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "seeker_email",
        "job_title",
        "status",
        "submitted_at",
        "last_status_change_at",
        "is_deleted",
    )
    list_filter = ("status", "is_deleted")
    search_fields = (
        "seeker__user__email",
        "seeker__full_name",
        "job__title",
        "job__company__name",
    )
    raw_id_fields = ("seeker", "job")
    readonly_fields = (
        "submitted_at",
        "last_status_change_at",
        "is_deleted",
        "deleted_at",
    )
    date_hierarchy = "submitted_at"
    inlines = [StatusHistoryInline]

    def get_queryset(self, request):
        # seeker_email and job_title each traverse two relations — join them upfront.
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


@admin.register(ApplicationStatusHistory)
class ApplicationStatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "application",
        "from_status",
        "to_status",
        "changed_by",
        "created_at",
    )
    list_filter = ("to_status",)
    raw_id_fields = ("application", "changed_by")
    readonly_fields = (
        "application",
        "from_status",
        "to_status",
        "changed_by",
        "notes",
        "created_at",
    )

    def has_add_permission(self, request):
        return False
