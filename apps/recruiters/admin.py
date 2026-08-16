from django.contrib import admin
from django.utils import timezone

from .models import Company, RecruiterProfile

from apps.core.admin import SoftDeleteAdminMixin 
@admin.register(Company)
class CompanyAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'industry', 'size', 'is_verified', 'created_at')
    list_filter = ('is_verified', 'size', 'industry', 'is_deleted')
    search_fields = ('name', 'website')
    raw_id_fields = ('industry', 'created_by')
    readonly_fields = ('verified_at', 'slug')
    actions = ['verify_companies']

    @admin.action(description='Mark selected companies as verified')
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
        'full_name', 'user_email', 'company',
        'position', 'is_company_admin', 'contact_visibility',
    )
    list_filter = ('is_company_admin', 'contact_visibility')
    search_fields = ('full_name', 'user__email', 'company__name')
    raw_id_fields = ('user', 'company')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'company')

    @admin.display(description='Email')
    def user_email(self, obj):
        return obj.user.email