from django.contrib import admin

from .models import Education, SeekerProfile, SeekerSkill, WorkExperience


class WorkExperienceInline(admin.TabularInline):
    model = WorkExperience
    extra = 0


class EducationInline(admin.TabularInline):
    model = Education
    extra = 0


class SeekerSkillInline(admin.TabularInline):
    model = SeekerSkill
    extra = 0
    # Requires search_fields on SkillAdmin (defined in apps/skills/admin.py).
    autocomplete_fields = ["skill"]


@admin.register(SeekerProfile)
class SeekerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "user_email",
        "current_title",
        "availability_status",
        "visibility",
        "is_deleted",
    )
    list_filter = ("availability_status", "visibility", "is_deleted")
    search_fields = ("full_name", "user__email", "current_title")
    raw_id_fields = ("user",)
    inlines = [SeekerSkillInline, WorkExperienceInline, EducationInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    @admin.display(description="Email")
    def user_email(self, obj):
        return obj.user.email
