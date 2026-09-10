from django.core.management.base import BaseCommand

from apps.jobs.models import JobCategory

CATEGORIES = {
    "Engineering": [
        "Backend Development",
        "Frontend Development",
        "Full Stack",
        "Mobile Development",
        "DevOps & Cloud",
        "Data Engineering",
        "Machine Learning",
        "QA & Testing",
        "Embedded Systems",
    ],
    "Design": [
        "UI/UX Design",
        "Graphic Design",
        "Product Design",
        "Motion Design",
    ],
    "Product": [
        "Product Management",
        "Product Marketing",
        "Business Analyst",
    ],
    "Sales & Marketing": [
        "Sales",
        "Marketing",
        "Content Writing",
        "SEO",
        "Digital Marketing",
        "Business Development",
    ],
    "Operations": [
        "Operations",
        "Customer Support",
        "HR",
        "Finance",
        "Admin",
    ],
    "Data": [
        "Data Analyst",
        "Data Scientist",
        "BI Developer",
    ],
}


class Command(BaseCommand):
    help = "Seed initial job categories"

    def handle(self, *args, **options):
        created = 0
        for parent_name, children in CATEGORIES.items():
            parent, was_created = JobCategory.objects.get_or_create(
                name=parent_name,
                parent=None,
                defaults={"is_active": True},
            )
            if was_created:
                created += 1

            for child_name in children:
                _, was_created = JobCategory.objects.get_or_create(
                    name=child_name,
                    parent=parent,
                    defaults={"is_active": True},
                )
                if was_created:
                    created += 1

        self.stdout.write(self.style.SUCCESS(f"Seeded {created} new categories."))
