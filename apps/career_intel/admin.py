from django.contrib import admin

from .models import (
    CareerPathEdge,
    CareerPathNode,
    LearningProvider,
    LearningResource,
    ResourceSkill,
    SalarySubmission,
    SkillGapSnapshot,
    TargetRole,
    TargetRoleSkill,
    UserLearning,
)


class TargetRoleSkillInline(admin.TabularInline):
    """Edit a role's required skills directly on the role page."""

    model = TargetRoleSkill
    extra = 0
    autocomplete_fields = ["skill"]


@admin.register(TargetRole)
class TargetRoleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "min_experience_years",
        "avg_salary_inr",
        "is_active",
        "sort_order",
    )
    list_filter = ("category", "is_active")
    search_fields = ("name", "slug")
    list_editable = ("is_active", "sort_order")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [TargetRoleSkillInline]


@admin.register(TargetRoleSkill)
class TargetRoleSkillAdmin(admin.ModelAdmin):
    list_display = ("target_role", "skill", "importance", "difficulty")
    list_filter = ("importance", "difficulty")
    search_fields = ("target_role__name", "skill__name")
    autocomplete_fields = ["target_role", "skill"]


@admin.register(SkillGapSnapshot)
class SkillGapSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "seeker_email",
        "target_role",
        "gap_score",
        "matched_count",
        "missing_critical_count",
        "created_at",
    )
    list_filter = ("target_role",)
    search_fields = ("seeker__user__email", "target_role__name")
    raw_id_fields = ("seeker", "target_role")
    readonly_fields = (
        "public_id",
        "gap_score",
        "total_required_skills",
        "matched_count",
        "missing_critical_count",
        "missing_important_count",
        "matched_skills",
        "missing_skills",
    )

    @admin.display(description="Seeker")
    def seeker_email(self, obj):
        return obj.seeker.user.email


# ---------------------------------------------------------------------------
# Feature 13 - Learning Recommendations
# ---------------------------------------------------------------------------


@admin.register(LearningProvider)
class LearningProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "trust_score", "is_active")
    list_editable = ("trust_score", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


class ResourceSkillInline(admin.TabularInline):
    """Edit which skills a resource teaches, right on the resource page."""

    model = ResourceSkill
    extra = 0
    autocomplete_fields = ["skill"]


@admin.register(LearningResource)
class LearningResourceAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "kind",
        "difficulty",
        "is_free",
        "external_rating",
        "quality_score",
        "is_endorsed",
        "is_active",
    )
    list_filter = ("kind", "difficulty", "is_free", "is_endorsed", "is_active")
    search_fields = ("title", "description", "url")
    list_editable = ("quality_score", "is_endorsed", "is_active")
    autocomplete_fields = ["provider"]
    inlines = [ResourceSkillInline]


@admin.register(UserLearning)
class UserLearningAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "resource_title",
        "status",
        "progress_pct",
        "user_rating",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("user__email", "resource__title")
    raw_id_fields = ("user", "resource")

    @admin.display(description="Resource")
    def resource_title(self, obj):
        return obj.resource.title[:60]


# =============================================================================
# STEP 8 -- Append this to: apps/career_intel/admin.py
#
# Required imports at the top of admin.py (add only what is missing):
#     from django.contrib import admin
#     from .models import SalarySubmission
# =============================================================================


@admin.register(SalarySubmission)
class SalarySubmissionAdmin(admin.ModelAdmin):
    """Admin surface for data quality: verify good entries, flag suspicious ones."""

    list_display = (
        "id",
        "role_title",
        "location_city",
        "salary_lpa_display",
        "experience_years_bucket",
        "company_size_bucket",
        "effective_year",
        "is_verified",
        "is_flagged",
        "submitted_at",
    )
    list_filter = (
        "is_verified",
        "is_flagged",
        "experience_years_bucket",
        "company_size_bucket",
        "employment_type",
        "work_arrangement",
    )
    search_fields = ("role_title", "location_city", "user__email")
    raw_id_fields = ("user", "target_role", "industry")

    # The user link and timestamp are set by the system and must not be edited.
    readonly_fields = ("user", "submitted_at")

    actions = ["mark_verified", "flag_suspicious"]

    @admin.display(description="Salary")
    def salary_lpa_display(self, obj):
        return f"₹{float(obj.salary_inr) / 100000:.1f}L"

    @admin.action(description="Mark selected submissions as verified")
    def mark_verified(self, request, queryset):
        count = queryset.update(is_verified=True)
        self.message_user(request, f"Marked {count} submissions as verified.")

    @admin.action(description="Flag selected as suspicious (excluded from aggregates)")
    def flag_suspicious(self, request, queryset):
        count = queryset.update(is_flagged=True)
        self.message_user(request, f"Flagged {count} submissions as suspicious.")


# =============================================================================
# STEP 8 -- Append this to: apps/career_intel/admin.py
#
# Required imports at the top of admin.py (add only what is missing):
#     from django.contrib import admin
#     from .models import CareerPathNode, CareerPathEdge
#
# IMPORTANT: CareerPathEdgeAdmin uses autocomplete_fields for from_node,
# to_node and required_skills. Django requires every autocompleted model to
# define search_fields on its own ModelAdmin:
#   - CareerPathNode  -> covered below
#   - Skill           -> SkillAdmin must have search_fields, e.g. ('name',)
# Without that, Django raises admin.E040 at system check time.
# =============================================================================


@admin.register(CareerPathNode)
class CareerPathNodeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "level",
        "category",
        "typical_experience_years",
        "avg_salary_inr",
        "is_active",
    )
    list_filter = ("level", "category", "is_active")
    search_fields = ("name", "slug")  # Also required by autocomplete on edges.
    list_editable = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(CareerPathEdge)
class CareerPathEdgeAdmin(admin.ModelAdmin):
    list_display = (
        "from_node",
        "to_node",
        "transition_type",
        "weight",
        "time_months",
        "is_active",
    )
    list_filter = ("transition_type", "is_active")
    search_fields = ("from_node__name", "to_node__name")
    autocomplete_fields = ["from_node", "to_node", "required_skills"]
    list_editable = ("is_active",)
    list_select_related = ("from_node", "to_node")


@admin.register(ResourceSkill)
class ResourceSkillAdmin(admin.ModelAdmin):
    """Standalone view, mainly for reverse lookups: which resources teach a skill."""

    list_display = ("skill", "resource", "get_provider")
    list_filter = ("skill",)
    search_fields = ("skill__name", "resource__title")
    list_select_related = ("skill", "resource", "resource__provider")
    autocomplete_fields = ("skill", "resource")

    @admin.display(description="Provider", ordering="resource__provider__name")
    def get_provider(self, obj):
        return obj.resource.provider.name
