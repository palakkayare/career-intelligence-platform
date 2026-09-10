"""
Seed the badge definitions.

Thresholds are set so that the first badge arrives early - a badge nobody
can reach in their first session teaches people the system is not for them -
and the last one takes real use.

Idempotent: re-running updates rather than duplicates.
"""
from django.core.management.base import BaseCommand

from apps.gamification.models import Badge

B = Badge

BADGES = [
    # Profile - the first one lands almost immediately on purpose.
    ('profile-started', 'Getting Started',
     'Filled in the basics of your profile.', B.Category.PROFILE, 25, 10, 10),
    ('profile-half', 'Half Way There',
     'Your profile is 50% complete.', B.Category.PROFILE, 50, 20, 20),
    ('profile-complete', 'Fully Loaded',
     'Your profile is 100% complete.', B.Category.PROFILE, 100, 50, 30),

    # Skills
    ('skills-5', 'Five Skills',
     'Added five skills to your profile.', B.Category.SKILLS, 5, 15, 10),
    ('skills-10', 'Well Rounded',
     'Added ten skills to your profile.', B.Category.SKILLS, 10, 30, 20),

    # Applications - milestones, not a volume race. There is deliberately
    # nothing above 25; rewarding the hundredth application would reward
    # spraying.
    ('first-application', 'First Step',
     'Sent your first application.', B.Category.APPLICATIONS, 1, 20, 10),
    ('applications-10', 'In The Running',
     'Sent ten applications.', B.Category.APPLICATIONS, 10, 40, 20),
    ('applications-25', 'Persistent',
     'Sent twenty-five applications.', B.Category.APPLICATIONS, 25, 75, 30),
]


class Command(BaseCommand):
    help = 'Seed badge definitions (idempotent)'

    def handle(self, *args, **options):
        for code, name, description, category, threshold, points, order in BADGES:
            Badge.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'description': description,
                    'category': category,
                    'threshold': threshold,
                    'points': points,
                    'sort_order': order,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(f'Seeded {len(BADGES)} badges.')
        )
