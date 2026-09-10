"""
Seed the initial set of target roles.

Curated for the common Indian tech market. Re-runnable: existing roles and
skill links are updated in place, not duplicated.
"""

import copy
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.career_intel.models import TargetRole, TargetRoleSkill
from apps.skills.models import Skill

# Skill tuple format: (skill_name, importance, difficulty, rationale)
ROLE_DATA = [
    {
        "name": "Senior Backend Developer",
        "slug": "senior-backend-developer",
        "description": ("Build scalable backend services for high-traffic applications."),
        "category": TargetRole.Category.ENGINEERING,
        "min_experience_years": 4,
        "typical_experience_years": 6,
        "avg_salary_inr": Decimal("2500000"),
        "skills": [
            ("Python", "critical", "medium", "Core language"),
            ("Django", "critical", "medium", "Most popular Python framework"),
            ("PostgreSQL", "critical", "medium", "Production-grade database"),
            ("Redis", "important", "easy", "Caching and message broker"),
            ("Docker", "important", "easy", "Standard containerization"),
            ("AWS", "important", "medium", "Cloud deployment"),
            ("Git", "critical", "easy", "Version control"),
            ("Linux", "important", "medium", "Server environments"),
            ("Kubernetes", "preferred", "hard", "Container orchestration"),
            ("Microservices", "preferred", "hard", "Architecture pattern"),
            ("CI/CD", "important", "medium", "Deployment automation"),
        ],
    },
    {
        "name": "Senior Frontend Developer",
        "slug": "senior-frontend-developer",
        "description": "Build modern, responsive user interfaces.",
        "category": TargetRole.Category.ENGINEERING,
        "min_experience_years": 3,
        "typical_experience_years": 5,
        "avg_salary_inr": Decimal("2200000"),
        "skills": [
            ("JavaScript", "critical", "medium", "Core language"),
            ("TypeScript", "critical", "medium", "Industry standard"),
            ("React", "critical", "medium", "Most popular framework"),
            ("Next.js", "important", "medium", "Production React framework"),
            ("Git", "critical", "easy", "Version control"),
            ("CSS", "important", "medium", "Styling fundamentals"),
            ("Vue.js", "optional", "medium", "Alternative to React"),
        ],
    },
    {
        "name": "Full Stack Developer",
        "slug": "full-stack-developer",
        "description": "Build end-to-end web applications.",
        "category": TargetRole.Category.ENGINEERING,
        "min_experience_years": 2,
        "typical_experience_years": 4,
        "avg_salary_inr": Decimal("1800000"),
        "skills": [
            ("JavaScript", "critical", "medium", None),
            ("React", "critical", "medium", None),
            ("Python", "important", "medium", None),
            ("Django", "important", "medium", None),
            ("PostgreSQL", "critical", "medium", None),
            ("Git", "critical", "easy", None),
            ("Docker", "preferred", "easy", None),
            ("AWS", "preferred", "medium", None),
        ],
    },
    {
        "name": "DevOps Engineer",
        "slug": "devops-engineer",
        "description": ("Build and maintain CI/CD, infrastructure, and deployments."),
        "category": TargetRole.Category.ENGINEERING,
        "min_experience_years": 3,
        "typical_experience_years": 5,
        "avg_salary_inr": Decimal("2400000"),
        "skills": [
            ("Linux", "critical", "medium", None),
            ("Docker", "critical", "easy", None),
            ("Kubernetes", "critical", "hard", None),
            ("AWS", "critical", "medium", None),
            ("CI/CD", "critical", "medium", None),
            ("Git", "critical", "easy", None),
            ("Python", "important", "medium", "Scripting"),
            ("Google Cloud", "preferred", "medium", None),
        ],
    },
    {
        "name": "Data Scientist",
        "slug": "data-scientist",
        "description": "Analyze data, build ML models, and derive insights.",
        "category": TargetRole.Category.DATA,
        "min_experience_years": 2,
        "typical_experience_years": 4,
        "avg_salary_inr": Decimal("2000000"),
        "skills": [
            ("Python", "critical", "medium", None),
            ("PostgreSQL", "important", "medium", None),
            ("Machine Learning", "critical", "hard", None),
            ("Git", "critical", "easy", None),
        ],
    },
    {
        "name": "Product Manager",
        "slug": "product-manager",
        "description": "Drive product strategy, roadmap, and execution.",
        "category": TargetRole.Category.PRODUCT,
        "min_experience_years": 2,
        "typical_experience_years": 5,
        "avg_salary_inr": Decimal("2800000"),
        "skills": [
            ("Communication", "critical", "medium", None),
            ("Leadership", "important", "medium", None),
            ("Problem Solving", "critical", "medium", None),
            ("JIRA", "important", "easy", None),
        ],
    },
    {
        "name": "UI/UX Designer",
        "slug": "ui-ux-designer",
        "description": "Design user-centric interfaces and experiences.",
        "category": TargetRole.Category.DESIGN,
        "min_experience_years": 2,
        "typical_experience_years": 4,
        "avg_salary_inr": Decimal("1500000"),
        "skills": [
            ("Figma", "critical", "easy", None),
            ("UI/UX Design", "critical", "medium", None),
            ("Adobe XD", "preferred", "easy", None),
            ("Photoshop", "optional", "easy", None),
        ],
    },
]


class Command(BaseCommand):
    help = "Seed the initial target roles with their skill requirements"

    @transaction.atomic
    def handle(self, *args, **options):
        created_roles = 0
        created_links = 0
        missing_skills = []

        # Work on a copy so the module-level ROLE_DATA is never mutated
        for idx, data in enumerate(copy.deepcopy(ROLE_DATA)):
            skills_data = data.pop("skills", [])

            role, was_created = TargetRole.objects.update_or_create(
                slug=data["slug"],
                defaults={
                    **data,
                    "is_active": True,
                    "sort_order": idx + 1,
                },
            )
            if was_created:
                created_roles += 1

            # Wire up the required skills
            for skill_name, importance, difficulty, rationale in skills_data:
                try:
                    skill = Skill.objects.get(name__iexact=skill_name)
                except Skill.DoesNotExist:
                    missing_skills.append((role.name, skill_name))
                    self.stderr.write(
                        f"WARNING: skill '{skill_name}' not found, " f"skipping it for {role.name}"
                    )
                    continue

                _, link_created = TargetRoleSkill.objects.update_or_create(
                    target_role=role,
                    skill=skill,
                    defaults={
                        "importance": importance,
                        "difficulty": difficulty,
                        "rationale": rationale or "",
                    },
                )
                if link_created:
                    created_links += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_roles} new role(s) and " f"{created_links} new skill link(s)."
            )
        )
        if missing_skills:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(missing_skills)} skill link(s) were skipped because the "
                    f"skill does not exist in the Skill table yet."
                )
            )
