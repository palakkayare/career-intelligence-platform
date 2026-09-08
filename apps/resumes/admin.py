from django.contrib import admin

from .models import Resume, ResumeSkill


class ResumeSkillInline(admin.TabularInline):
    """Shows extracted skills inline on the resume page."""

    model = ResumeSkill
    extra = 0
    fields = ('skill', 'confidence', 'source', 'is_confirmed', 'is_user_added')
    # These come from the parser, so an admin should not edit them by hand
    readonly_fields = ('confidence', 'source', 'is_user_added')
    autocomplete_fields = ['skill']


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'user_email', 'is_primary', 'status',
        'ats_score', 'advanced_ats_score', 'parsed_at', 'created_at',
    )
    list_filter = ('status', 'is_primary', 'is_deleted')
    search_fields = ('name', 'user__email', 'original_filename')
    raw_id_fields = ('user',)
    # Everything the parser produced is read-only: editing it would
    # silently disagree with the stored file
    readonly_fields = (
        'public_id', 'file', 'original_filename', 'file_size_bytes',
        'status', 'extracted_text', 'parsed_data',
        'ats_score', 'ats_breakdown',
        'advanced_ats_score', 'advanced_ats_breakdown',
        'advanced_ats_analyzed_at',
        'failure_reason', 'parse_attempts', 'parsed_at',
    )
    inlines = [ResumeSkillInline]
    actions = ['retrigger_parsing']

    @admin.display(description='User')
    def user_email(self, obj):
        return obj.user.email

    @admin.action(description='Re-trigger parsing for selected resumes')
    def retrigger_parsing(self, request, queryset):
        """Useful when parsing failed or the parser itself was improved."""
        from .tasks import parse_resume_task

        count = 0
        for resume in queryset:
            resume.status = Resume.Status.PENDING
            resume.save(update_fields=['status'])
            parse_resume_task.delay(resume.id)
            count += 1

        self.message_user(request, f"Re-parsing {count} resumes.")


@admin.register(ResumeSkill)
class ResumeSkillAdmin(admin.ModelAdmin):
    list_display = (
        'resume', 'skill', 'confidence', 'source',
        'is_confirmed', 'is_user_added',
    )
    list_filter = ('source', 'is_confirmed', 'is_user_added')
    search_fields = ('resume__name', 'skill__name')
    raw_id_fields = ('resume', 'skill')
    
