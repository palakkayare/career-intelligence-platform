from django.contrib import admin

from .models import (
    CompanyResponse,
    CompanyReview,
    InterviewExperience,
    ReviewHelpfulVote,
    ReviewReport,
)


class ReviewReportInline(admin.TabularInline):
    model = ReviewReport
    extra = 0
    readonly_fields = ('reported_by', 'reason', 'detail', 'created_at')
    fields = ('reason', 'detail', 'reviewed_by_admin', 'admin_notes',
              'created_at')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(CompanyReview)
class CompanyReviewAdmin(admin.ModelAdmin):
    list_display = ('headline', 'company', 'overall_rating', 'status',
                    'report_count', 'is_verified_employee', 'created_at')
    list_filter = ('status', 'is_verified_employee', 'employment_status',
                   'would_recommend')
    search_fields = ('headline', 'pros', 'cons', 'company__name')
    raw_id_fields = ('company', 'author')
    date_hierarchy = 'created_at'
    inlines = [ReviewReportInline]
    actions = ['restore_reviews', 'remove_reviews']

    @admin.action(description='Restore selected reviews (reports dismissed)')
    def restore_reviews(self, request, queryset):
        from .services import ModerationService

        for review in queryset:
            ModerationService.restore(review, f'Restored by {request.user.email}')
        self.message_user(request, f'{queryset.count()} review(s) restored.')

    @admin.action(description='Remove selected reviews')
    def remove_reviews(self, request, queryset):
        from .services import ModerationService

        for review in queryset:
            ModerationService.remove(review, f'Removed by {request.user.email}')
        self.message_user(request, f'{queryset.count()} review(s) removed.')


@admin.register(InterviewExperience)
class InterviewExperienceAdmin(admin.ModelAdmin):
    list_display = ('role_applied', 'company', 'outcome', 'difficulty',
                    'status', 'created_at')
    list_filter = ('outcome', 'difficulty', 'status')
    search_fields = ('role_applied', 'process', 'company__name')
    raw_id_fields = ('company', 'author')


@admin.register(CompanyResponse)
class CompanyResponseAdmin(admin.ModelAdmin):
    list_display = ('review', 'responder_name', 'responder_title', 'created_at')
    search_fields = ('response', 'responder_name')
    raw_id_fields = ('review', 'responder')


@admin.register(ReviewReport)
class ReviewReportAdmin(admin.ModelAdmin):
    list_display = ('review', 'reason', 'reviewed_by_admin', 'created_at')
    list_filter = ('reason', 'reviewed_by_admin')
    raw_id_fields = ('review', 'reported_by')

    def has_add_permission(self, request):
        return False


@admin.register(ReviewHelpfulVote)
class ReviewHelpfulVoteAdmin(admin.ModelAdmin):
    list_display = ('review', 'user', 'created_at')
    raw_id_fields = ('review', 'user')

    def has_add_permission(self, request):
        return False
