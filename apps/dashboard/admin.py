from django.contrib import admin

from .models import SeekerDashboardState


@admin.register(SeekerDashboardState)
class SeekerDashboardStateAdmin(admin.ModelAdmin):
    list_display = ("seeker", "last_seen_at", "updated_at")
    search_fields = ("seeker__user__email", "seeker__full_name")
    raw_id_fields = ("seeker",)
