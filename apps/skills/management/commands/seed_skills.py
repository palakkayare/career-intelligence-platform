"""
Seed the skill taxonomy.

    python manage.py seed_skills

Safe to run again: existing skills are updated in place, nothing is
duplicated, and skills people added themselves are left alone.

Three features read from this table and nothing else - match scores, the
skill gap, and learning resources - so a thin table does not break them, it
quietly empties them.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.skills.data.skill_catalogue import SKILLS, SLUG_OVERRIDES
from apps.skills.models import Skill


class Command(BaseCommand):
    help = "Seed the skill taxonomy (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        existing = {s.name.lower(): s for s in Skill.objects.all()}

        created = updated = unchanged = 0

        for name, category, aliases in SKILLS:
            current = existing.get(name.lower())

            if current is None:
                if not dry_run:
                    defaults = {"category": category, "aliases": aliases, "is_approved": True}
                    if name in SLUG_OVERRIDES:
                        defaults["slug"] = SLUG_OVERRIDES[name]
                    Skill.objects.create(name=name, **defaults)
                created += 1
                continue

            # Keep any aliases a human added; add the ones we ship.
            merged = sorted({*(current.aliases or []), *aliases})
            changed = merged != sorted(current.aliases or []) or current.category != category

            if changed and not dry_run:
                current.aliases = merged
                current.category = category
                current.is_approved = True
                current.save(update_fields=["aliases", "category", "is_approved"])

            updated += 1 if changed else 0
            unchanged += 0 if changed else 1

        total = Skill.objects.count() + (created if dry_run else 0)
        prefix = "Would seed" if dry_run else "Seeded"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}: {created} new, {updated} updated, {unchanged} unchanged. "
                f"Catalogue has {len(SKILLS)} skills; the table now holds {total}."
            )
        )
