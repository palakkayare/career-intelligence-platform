from django.contrib import admin

from .models import Industry


@admin.register(Industry)
class IndustryAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "is_active")
    search_fields = ("name", "aliases")
    prepopulated_fields = {"slug": ("name",)}
    # Editable directly from the list view — handy for reordering the dropdown.
    list_editable = ("sort_order", "is_active")
