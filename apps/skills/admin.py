from django.contrib import admin, messages

from .models import Skill
from .services import SkillMergeService


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "alias_list",
        "usage_count",
        "is_approved",
        "is_deprecated",
    )
    list_filter = ("category", "is_approved", "is_deprecated")
    # Deliberately not searching `aliases`: it is a JSONField, and admin
    # search would turn every quote and bracket in the stored JSON into a
    # match. Aliases are shown in the list instead.
    search_fields = ("name", "slug")
    list_editable = ("is_approved", "is_deprecated")
    actions = ["merge_into_first", "approve_selected"]

    @admin.display(description="Aliases")
    def alias_list(self, obj):
        return ", ".join(obj.aliases or []) or "—"

    @admin.display(description="In use by")
    def usage_count(self, obj):
        return obj.seeker_skills.count()

    @admin.action(description="Merge selected into the most-used one")
    def merge_into_first(self, request, queryset):
        """
        Blueprint Feature 10: skill taxonomy management - add, merge,
        deprecate. This is the merge half.
        """
        skills = list(queryset)

        if len(skills) < 2:
            self.message_user(
                request,
                "Select at least two skills to merge.",
                level=messages.WARNING,
            )
            return

        # The most-used row survives: fewer references to move, and the
        # surviving name is the one people actually type.
        ranked = sorted(skills, key=lambda s: s.seeker_skills.count(), reverse=True)
        target, sources = ranked[0], ranked[1:]

        for source in sources:
            try:
                result = SkillMergeService.merge(source, target)
                self.message_user(
                    request,
                    f'Merged "{result["source"]}" into "{result["target"]}" '
                    f'({result["moved"]})',
                    level=messages.SUCCESS,
                )
            except Exception as exc:
                self.message_user(
                    request,
                    f"Could not merge {source.name}: {exc}",
                    level=messages.ERROR,
                )

    @admin.action(description="Approve selected skills")
    def approve_selected(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"{updated} skill(s) approved.")
