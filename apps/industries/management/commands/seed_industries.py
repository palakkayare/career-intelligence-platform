from django.core.management.base import BaseCommand

from apps.industries.models import Industry


INITIAL_INDUSTRIES = [
    ('Information Technology', ['IT', 'Tech', 'Software']),
    ('Banking & Financial Services', ['Banking', 'Finance', 'BFSI']),
    ('E-commerce', ['Ecommerce', 'Online Retail']),
    ('Healthcare', ['Health', 'Medical', 'Pharma']),
    ('Education', ['EdTech', 'Education Tech']),
    ('Manufacturing', ['Production', 'Industrial']),
    ('Consulting', []),
    ('Real Estate', ['Property', 'PropTech']),
    ('Media & Entertainment', ['Media', 'Entertainment']),
    ('Retail', []),
    ('Telecommunications', ['Telecom']),
    ('Hospitality & Travel', ['Hospitality', 'Travel', 'Tourism']),
    ('Logistics & Supply Chain', ['Logistics', 'Supply Chain']),
    ('Automotive', ['Auto']),
    ('Energy & Utilities', ['Energy', 'Utilities', 'Power']),
    ('Government & Public Sector', ['Government', 'Public Sector']),
    ('Non-Profit', ['NGO', 'Non Profit']),
    ('Agriculture', ['AgriTech']),
    ('Legal Services', ['Legal', 'Law']),
    ('Marketing & Advertising', ['Marketing', 'Advertising', 'AdTech']),
    ('Other', []),
]


class Command(BaseCommand):
    help = 'Seed initial industry taxonomy'

    def handle(self, *args, **options):
        created = 0
        for idx, (name, aliases) in enumerate(INITIAL_INDUSTRIES):
            obj, was_created = Industry.objects.update_or_create(
                name=name,
                defaults={
                    'aliases': aliases,
                    'sort_order': idx + 1,
                    'is_active': True,
                },
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created} new industries (total: {len(INITIAL_INDUSTRIES)})."
        ))