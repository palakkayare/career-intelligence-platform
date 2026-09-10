from django.contrib import admin

from .models import (
    ChecklistProgress,
    CompanyInterviewTip,
    InterviewChecklistItem,
    InterviewQuestion,
    NegotiationScript,
    StarTemplate,
)


@admin.register(InterviewQuestion)
class InterviewQuestionAdmin(admin.ModelAdmin):
    list_display = ('question', 'target_role', 'category', 'difficulty',
                    'asked_frequency', 'is_active')
    list_filter = ('category', 'difficulty', 'is_active')
    search_fields = ('question', 'guidance')
    list_editable = ('asked_frequency', 'is_active')
    raw_id_fields = ('target_role',)


@admin.register(StarTemplate)
class StarTemplateAdmin(admin.ModelAdmin):
    list_display = ('competency', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('competency', 'description')


@admin.register(CompanyInterviewTip)
class CompanyInterviewTipAdmin(admin.ModelAdmin):
    list_display = ('company', 'category', 'source', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('tip', 'company__name')
    raw_id_fields = ('company',)


@admin.register(NegotiationScript)
class NegotiationScriptAdmin(admin.ModelAdmin):
    list_display = ('title', 'scenario', 'is_active')
    list_filter = ('scenario', 'is_active')


@admin.register(InterviewChecklistItem)
class InterviewChecklistItemAdmin(admin.ModelAdmin):
    list_display = ('text', 'phase', 'order', 'is_active')
    list_filter = ('phase', 'is_active')
    list_editable = ('order', 'is_active')


@admin.register(ChecklistProgress)
class ChecklistProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'interview_label', 'item', 'completed_at')
    search_fields = ('user__email', 'interview_label')
    raw_id_fields = ('user', 'item')

    def has_add_permission(self, request):
        return False
