from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.core.admin import SoftDeleteAdminMixin

from .models import BackupCode, LoginHistory, OTPCode, TwoFactorAuth, User


@admin.register(User)
class UserAdmin(SoftDeleteAdminMixin, DjangoUserAdmin):
    """Custom admin for our User model (replaces Django's default UserAdmin)."""

    list_display = (
        "email",
        "role",
        "auth_provider",
        "is_email_verified",
        "is_2fa_enabled",
        "is_active",
        "date_joined",
    )
    list_filter = (
        "role",
        "auth_provider",
        "is_email_verified",
        "is_2fa_enabled",
        "is_staff",
        "is_superuser",
        "is_active",
        "is_deleted",
    )
    search_fields = ("email", "full_name", "public_id")
    ordering = ("-date_joined",)
    readonly_fields = (
        "public_id",
        "date_joined",
        "last_login",
        "google_sub",
        "deleted_at",
    )

    # Field groups shown on the "change user" page
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Identity",
            {
                "fields": ("public_id", "role", "full_name", "profile_picture_url"),
            },
        ),
        (
            "Authentication",
            {
                "fields": (
                    "auth_provider",
                    "google_sub",
                    "is_email_verified",
                    "is_2fa_enabled",
                ),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Mobile", {"fields": ("fcm_token",)}),
        ("Soft delete", {"fields": ("is_deleted", "deleted_at")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    # Field groups shown on the "add user" page
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "role"),
            },
        ),
    )


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "purpose",
        "is_used",
        "attempts",
        "expires_at",
        "created_at",
    )
    list_filter = ("purpose", "is_used")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)
    readonly_fields = ("code", "created_at", "used_at")


@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = ("email_attempted", "status", "ip_address", "created_at")
    list_filter = ("status",)
    search_fields = ("email_attempted", "ip_address")
    raw_id_fields = ("user",)
    readonly_fields = (
        "user",
        "email_attempted",
        "status",
        "ip_address",
        "user_agent",
        "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        # Login history is written by the auth flow only — never created by hand.
        return False

    def has_change_permission(self, request, obj=None):
        # Audit data must stay immutable.
        return False


@admin.register(TwoFactorAuth)
class TwoFactorAuthAdmin(admin.ModelAdmin):
    list_display = ("user", "is_enabled", "enabled_at", "last_used_at")
    list_filter = ("is_enabled",)
    search_fields = ("user__email",)
    raw_id_fields = ("user",)
    readonly_fields = ("secret",)


@admin.register(BackupCode)
class BackupCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "is_used", "created_at", "used_at")
    list_filter = ("is_used",)
    search_fields = ("user__email",)
    raw_id_fields = ("user",)
    readonly_fields = ("code_hash", "created_at", "used_at")
