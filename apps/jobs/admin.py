from django.contrib import admin, messages

from .models import Job, JobCategory, SavedSearch, SearchHistory, Tag
from .services import JobStatusService


@admin.register(JobCategory)
class JobCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "sort_order", "is_active")
    list_filter = ("is_active", "parent")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "use_count", "created_at")
    search_fields = ("name",)
    ordering = ("-use_count",)
    readonly_fields = ("use_count",)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "company",
        "status",
        "employment_type",
        "application_count",
        "view_count",
        "activated_at",
        "is_deleted",
    )
    list_filter = (
        "status",
        "employment_type",
        "work_arrangement",
        "is_deleted",
        "company__is_verified",
    )
    search_fields = ("title", "description", "company__name")
    raw_id_fields = ("company", "posted_by", "category", "approved_by")
    readonly_fields = (
        "public_id",
        "view_count",
        "application_count",
        "submitted_at",
        "activated_at",
        "closed_at",
        "approved_by",
        "approved_at",
        "created_at",
        "updated_at",
        "search_vector",
    )
    date_hierarchy = "created_at"
    list_per_page = 50
    actions = ["approve_jobs", "reject_jobs", "expire_jobs"]

    # Job has three M2M fields. The default multi-select box is painful with 40+
    # skills; filter_horizontal gives a searchable two-pane picker instead.
    filter_horizontal = ("required_skills", "nice_to_have_skills", "tags")

    def get_queryset(self, request):
        # Avoid one extra query per row for the "company" column.
        return super().get_queryset(request).select_related("company", "category")

    @admin.action(description="Approve selected pending jobs")
    def approve_jobs(self, request, queryset):
        approved = 0
        for job in queryset.filter(status=Job.Status.PENDING_APPROVAL):
            try:
                JobStatusService.approve(job, actor=request.user)
                approved += 1
            except Exception as exc:
                self.message_user(
                    request,
                    f"Failed to approve {job}: {exc}",
                    messages.ERROR,
                )
        self.message_user(request, f"Approved {approved} job(s).", messages.SUCCESS)

    @admin.action(description="Reject selected pending jobs (default reason)")
    def reject_jobs(self, request, queryset):
        rejected = 0
        for job in queryset.filter(status=Job.Status.PENDING_APPROVAL):
            try:
                JobStatusService.reject(
                    job,
                    actor=request.user,
                    reason="Rejected via admin bulk action — please contact support.",
                )
                rejected += 1
            except Exception as exc:
                self.message_user(
                    request,
                    f"Failed to reject {job}: {exc}",
                    messages.ERROR,
                )
        self.message_user(request, f"Rejected {rejected} job(s).", messages.SUCCESS)

    @admin.action(description="Expire selected active jobs")
    def expire_jobs(self, request, queryset):
        expired = 0
        for job in queryset.filter(status=Job.Status.ACTIVE):
            try:
                JobStatusService.expire(job)
                expired += 1
            except Exception as exc:
                self.message_user(
                    request,
                    f"Failed to expire {job}: {exc}",
                    messages.ERROR,
                )
        self.message_user(request, f"Expired {expired} job(s).", messages.SUCCESS)


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "query_text", "last_executed_at", "created_at")
    search_fields = ("name", "user__email")
    raw_id_fields = ("user",)


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "query_text", "result_count", "created_at")
    search_fields = ("user__email", "query_text")
    raw_id_fields = ("user",)
    readonly_fields = ("user", "query_text", "filters", "result_count", "created_at")
