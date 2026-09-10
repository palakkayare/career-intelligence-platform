"""
Seed initial skills into the database.
Usage: python manage.py seed_skills
"""

from django.core.management.base import BaseCommand

from apps.skills.models import Skill, SkillCategory

SLUG_OVERRIDES = {
    "C++": "cpp",
    "C#": "csharp",
}
INITIAL_SKILLS = [
    # Programming Languages
    ("Python", SkillCategory.PROGRAMMING, ["py"]),
    ("JavaScript", SkillCategory.PROGRAMMING, ["js", "javascript"]),
    ("TypeScript", SkillCategory.PROGRAMMING, ["ts"]),
    ("Java", SkillCategory.PROGRAMMING, []),
    ("C++", SkillCategory.PROGRAMMING, ["cpp"]),
    ("C#", SkillCategory.PROGRAMMING, ["csharp"]),
    ("Go", SkillCategory.PROGRAMMING, ["golang"]),
    ("Ruby", SkillCategory.PROGRAMMING, []),
    ("PHP", SkillCategory.PROGRAMMING, []),
    ("Swift", SkillCategory.PROGRAMMING, []),
    ("Kotlin", SkillCategory.PROGRAMMING, []),
    # Frameworks
    ("Django", SkillCategory.FRAMEWORK, []),
    ("Flask", SkillCategory.FRAMEWORK, []),
    ("FastAPI", SkillCategory.FRAMEWORK, []),
    ("React", SkillCategory.FRAMEWORK, ["reactjs"]),
    ("Vue.js", SkillCategory.FRAMEWORK, ["vue"]),
    ("Angular", SkillCategory.FRAMEWORK, []),
    ("Next.js", SkillCategory.FRAMEWORK, ["nextjs"]),
    ("Express.js", SkillCategory.FRAMEWORK, ["express"]),
    ("Spring Boot", SkillCategory.FRAMEWORK, ["spring"]),
    ("Ruby on Rails", SkillCategory.FRAMEWORK, ["rails"]),
    ("Laravel", SkillCategory.FRAMEWORK, []),
    # Databases
    ("PostgreSQL", SkillCategory.DATABASE, ["postgres"]),
    ("MySQL", SkillCategory.DATABASE, []),
    ("MongoDB", SkillCategory.DATABASE, ["mongo"]),
    ("Redis", SkillCategory.DATABASE, []),
    ("SQLite", SkillCategory.DATABASE, []),
    ("Elasticsearch", SkillCategory.DATABASE, ["es"]),
    # Cloud & DevOps
    ("AWS", SkillCategory.CLOUD, ["amazon web services"]),
    ("Google Cloud", SkillCategory.CLOUD, ["gcp"]),
    ("Azure", SkillCategory.CLOUD, []),
    ("Docker", SkillCategory.CLOUD, []),
    ("Kubernetes", SkillCategory.CLOUD, ["k8s"]),
    ("CI/CD", SkillCategory.CLOUD, []),
    ("Linux", SkillCategory.CLOUD, []),
    ("Git", SkillCategory.CLOUD, []),
    # Design
    ("Figma", SkillCategory.DESIGN, []),
    ("Adobe XD", SkillCategory.DESIGN, []),
    ("Photoshop", SkillCategory.DESIGN, []),
    ("UI/UX Design", SkillCategory.DESIGN, ["ui design", "ux design"]),
    # Soft Skills
    ("Leadership", SkillCategory.SOFT_SKILL, []),
    ("Communication", SkillCategory.SOFT_SKILL, []),
    ("Problem Solving", SkillCategory.SOFT_SKILL, []),
    ("Team Collaboration", SkillCategory.SOFT_SKILL, ["teamwork"]),
    # Tools
    ("JIRA", SkillCategory.TOOL, []),
    ("Postman", SkillCategory.TOOL, []),
    ("Slack", SkillCategory.TOOL, []),
]


class Command(BaseCommand):
    help = "Seed initial skill taxonomy"

    def handle(self, *args, **options):
        created = 0
        for name, category, aliases in INITIAL_SKILLS:
            defaults = {
                "category": category,
                "aliases": aliases,
                "is_approved": True,
            }
            if name in SLUG_OVERRIDES:
                defaults["slug"] = SLUG_OVERRIDES[name]

            obj, was_created = Skill.objects.update_or_create(
                name=name,
                defaults=defaults,
            )
            if was_created:
                created += 1

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {created} new skills (total: {len(INITIAL_SKILLS)})")
        )
