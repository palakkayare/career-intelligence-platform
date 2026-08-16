from django.contrib import admin

from .models import Skill


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_approved', 'is_deprecated')
    list_filter = ('category', 'is_approved', 'is_deprecated')
    # search_fields is mandatory here — SeekerSkillInline's autocomplete depends on it.
    search_fields = ('name', 'aliases')
    prepopulated_fields = {'slug': ('name',)}