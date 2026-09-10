"""
Seed learning providers and curated learning resources.

Re-runnable: existing providers, resources, and skill links are updated in
place rather than duplicated.
"""

import copy
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.career_intel.models import LearningProvider, LearningResource, ResourceSkill
from apps.skills.models import Skill

# Format: (name, slug, website, trust_score)
PROVIDERS = [
    ("Coursera", "coursera", "https://coursera.org", 9),
    ("Udemy", "udemy", "https://udemy.com", 7),
    ("edX", "edx", "https://edx.org", 9),
    ("YouTube", "youtube", "https://youtube.com", 5),
    ("MDN Web Docs", "mdn", "https://developer.mozilla.org", 9),
    ("Official Docs", "official-docs", "", 10),
    ("FreeCodeCamp", "freecodecamp", "https://freecodecamp.org", 8),
    ("Educative", "educative", "https://educative.io", 8),
    ("A Cloud Guru", "a-cloud-guru", "https://acloudguru.com", 8),
    ("AWS Skill Builder", "aws-skill-builder", "https://skillbuilder.aws", 9),
]

# 'skills' format: [(skill_name, is_primary, coverage), ...]
RESOURCES = [
    # --- Python ---
    {
        "title": "Python for Everybody Specialization",
        "url": "https://www.coursera.org/specializations/python",
        "description": (
            "Beginner-friendly introduction to Python by the University of " "Michigan."
        ),
        "kind": "course",
        "difficulty": "beginner",
        "duration_hours": 60,
        "is_free": False,
        "price_inr": Decimal("3500"),
        "external_rating": 4.8,
        "quality_score": 92,
        "provider_slug": "coursera",
        "is_endorsed": True,
        "skills": [("Python", True, 95)],
    },
    {
        "title": "Automate the Boring Stuff with Python",
        "url": "https://automatetheboringstuff.com",
        "description": "Free book teaching Python through practical scripts.",
        "kind": "book",
        "difficulty": "beginner",
        "duration_hours": 30,
        "is_free": True,
        "external_rating": 4.7,
        "quality_score": 88,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("Python", True, 80)],
    },
    # --- Django ---
    {
        "title": "Django for Beginners",
        "url": "https://djangoforbeginners.com",
        "description": "Hands-on book by William Vincent.",
        "kind": "book",
        "difficulty": "beginner",
        "duration_hours": 25,
        "is_free": False,
        "price_inr": Decimal("2500"),
        "external_rating": 4.7,
        "quality_score": 90,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("Django", True, 95), ("Python", False, 30)],
    },
    {
        "title": "Django Official Tutorial",
        "url": "https://docs.djangoproject.com/en/stable/intro/tutorial01/",
        "description": "Build your first Django app step by step.",
        "kind": "tutorial",
        "difficulty": "beginner",
        "duration_hours": 8,
        "is_free": True,
        "external_rating": 4.5,
        "quality_score": 85,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("Django", True, 75)],
    },
    # --- Docker ---
    {
        "title": "Docker Mastery: with Kubernetes + Swarm",
        "url": "https://www.udemy.com/course/docker-mastery/",
        "description": (
            "Comprehensive Docker course with an introduction to Kubernetes, " "by Bret Fisher."
        ),
        "kind": "course",
        "difficulty": "beginner",
        "duration_hours": 22,
        "is_free": False,
        "price_inr": Decimal("1500"),
        "external_rating": 4.7,
        "quality_score": 90,
        "provider_slug": "udemy",
        "is_endorsed": True,
        "skills": [("Docker", True, 95), ("Kubernetes", False, 40)],
    },
    # --- Kubernetes ---
    {
        "title": "Kubernetes Up and Running",
        "url": ("https://www.oreilly.com/library/view/kubernetes-up-and/" "9781098110192/"),
        "description": "Definitive guide by Kelsey Hightower and others.",
        "kind": "book",
        "difficulty": "intermediate",
        "duration_hours": 40,
        "is_free": False,
        "external_rating": 4.6,
        "quality_score": 88,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("Kubernetes", True, 95)],
    },
    {
        "title": "Certified Kubernetes Administrator (CKA) Course",
        "url": ("https://acloudguru.com/course/" "certified-kubernetes-administrator-cka"),
        "description": "Preparation course for the CKA exam.",
        "kind": "course",
        "difficulty": "intermediate",
        "duration_hours": 30,
        "is_free": False,
        "price_inr": Decimal("4000"),
        "external_rating": 4.6,
        "quality_score": 86,
        "provider_slug": "a-cloud-guru",
        "is_endorsed": False,
        "skills": [("Kubernetes", True, 90)],
    },
    # --- AWS ---
    {
        "title": "AWS Certified Cloud Practitioner Essentials",
        "url": "https://explore.skillbuilder.aws/learn/course/134/",
        "description": "Free introduction to AWS, published by AWS itself.",
        "kind": "course",
        "difficulty": "beginner",
        "duration_hours": 6,
        "is_free": True,
        "external_rating": 4.6,
        "quality_score": 88,
        "provider_slug": "aws-skill-builder",
        "is_endorsed": True,
        "skills": [("AWS", True, 70)],
    },
    {
        "title": "AWS Certified Developer Associate",
        "url": ("https://www.udemy.com/course/" "aws-certified-developer-associate-dva-c01/"),
        "description": "Stephane Maarek's comprehensive AWS course.",
        "kind": "course",
        "difficulty": "intermediate",
        "duration_hours": 30,
        "is_free": False,
        "price_inr": Decimal("1500"),
        "external_rating": 4.7,
        "quality_score": 92,
        "provider_slug": "udemy",
        "is_endorsed": True,
        "skills": [("AWS", True, 90)],
    },
    # --- PostgreSQL ---
    {
        "title": "PostgreSQL Tutorial",
        "url": "https://www.postgresqltutorial.com",
        "description": "Free comprehensive PostgreSQL tutorial site.",
        "kind": "tutorial",
        "difficulty": "beginner",
        "duration_hours": 15,
        "is_free": True,
        "external_rating": 4.5,
        "quality_score": 85,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("PostgreSQL", True, 80)],
    },
    # --- JavaScript ---
    {
        "title": "JavaScript: The Definitive Guide",
        "url": ("https://www.oreilly.com/library/view/javascript-the-definitive/" "9781491952016/"),
        "description": "David Flanagan's classic comprehensive reference.",
        "kind": "book",
        "difficulty": "intermediate",
        "duration_hours": 50,
        "is_free": False,
        "external_rating": 4.6,
        "quality_score": 87,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("JavaScript", True, 95)],
    },
    {
        "title": "JavaScript Guide - MDN",
        "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",
        "description": "Free, authoritative JavaScript guide by Mozilla.",
        "kind": "documentation",
        "difficulty": "beginner",
        "duration_hours": 20,
        "is_free": True,
        "external_rating": 4.8,
        "quality_score": 92,
        "provider_slug": "mdn",
        "is_endorsed": True,
        "skills": [("JavaScript", True, 90)],
    },
    # --- React ---
    {
        "title": "React - The Complete Guide",
        "url": ("https://www.udemy.com/course/" "react-the-complete-guide-incl-redux/"),
        "description": (
            "Comprehensive Udemy course covering React and Redux, by " "Maximilian Schwarzmuller."
        ),
        "kind": "course",
        "difficulty": "beginner",
        "duration_hours": 50,
        "is_free": False,
        "price_inr": Decimal("1500"),
        "external_rating": 4.7,
        "quality_score": 91,
        "provider_slug": "udemy",
        "is_endorsed": True,
        "skills": [("React", True, 95)],
    },
    # --- Linux ---
    {
        "title": "The Linux Commands Handbook",
        "url": ("https://www.freecodecamp.org/news/the-linux-commands-handbook/"),
        "description": "Free comprehensive Linux command-line guide.",
        "kind": "tutorial",
        "difficulty": "beginner",
        "duration_hours": 8,
        "is_free": True,
        "external_rating": 4.5,
        "quality_score": 82,
        "provider_slug": "freecodecamp",
        "is_endorsed": True,
        "skills": [("Linux", True, 75)],
    },
    # --- Git ---
    {
        "title": "Pro Git Book",
        "url": "https://git-scm.com/book/en/v2",
        "description": ("Free official Git book, the most authoritative resource " "available."),
        "kind": "book",
        "difficulty": "beginner",
        "duration_hours": 15,
        "is_free": True,
        "external_rating": 4.8,
        "quality_score": 95,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("Git", True, 100)],
    },
    # --- Redis ---
    {
        "title": "Redis University: RU101",
        "url": "https://university.redis.com/courses/ru101/",
        "description": "Free introduction to Redis, published by Redis.",
        "kind": "course",
        "difficulty": "beginner",
        "duration_hours": 6,
        "is_free": True,
        "external_rating": 4.5,
        "quality_score": 85,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("Redis", True, 80)],
    },
    # --- CI/CD ---
    {
        "title": "GitHub Actions: The Complete Guide",
        "url": ("https://www.udemy.com/course/github-actions-the-complete-guide/"),
        "description": "Comprehensive CI/CD with GitHub Actions.",
        "kind": "course",
        "difficulty": "intermediate",
        "duration_hours": 12,
        "is_free": False,
        "price_inr": Decimal("1500"),
        "external_rating": 4.6,
        "quality_score": 86,
        "provider_slug": "udemy",
        "is_endorsed": False,
        "skills": [("CI/CD", True, 80)],
    },
    # --- System design / architecture ---
    {
        "title": "System Design Primer",
        "url": "https://github.com/donnemartin/system-design-primer",
        "description": "Large free GitHub repository on system design.",
        "kind": "documentation",
        "difficulty": "intermediate",
        "duration_hours": 50,
        "is_free": True,
        "external_rating": 4.9,
        "quality_score": 95,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("Microservices", False, 60)],
    },
    # --- TypeScript ---
    {
        "title": "TypeScript Handbook",
        "url": "https://www.typescriptlang.org/docs/handbook/intro.html",
        "description": ("Official TypeScript documentation, beginner through advanced."),
        "kind": "documentation",
        "difficulty": "beginner",
        "duration_hours": 12,
        "is_free": True,
        "external_rating": 4.7,
        "quality_score": 90,
        "provider_slug": "official-docs",
        "is_endorsed": True,
        "skills": [("TypeScript", True, 85)],
    },
]


class Command(BaseCommand):
    help = "Seed learning providers and curated learning resources"

    @transaction.atomic
    def handle(self, *args, **options):
        # --- Providers ---
        provider_objs = {}
        for name, slug, website, trust in PROVIDERS:
            obj, _ = LearningProvider.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "website": website,
                    "trust_score": trust,
                    "is_active": True,
                },
            )
            provider_objs[slug] = obj

        self.stdout.write(f"Providers ready: {len(provider_objs)}")

        # --- Resources ---
        created_resources = 0
        skill_links = 0
        missing_skills = []

        # Work on a copy so the module-level RESOURCES list is never mutated
        for data in copy.deepcopy(RESOURCES):
            skills = data.pop("skills", [])
            provider_slug = data.pop("provider_slug", None)
            provider = provider_objs.get(provider_slug)

            resource, was_created = LearningResource.objects.update_or_create(
                title=data["title"],
                defaults={
                    **data,
                    "provider": provider,
                    "is_active": True,
                },
            )
            if was_created:
                created_resources += 1

            for skill_name, is_primary, coverage in skills:
                try:
                    skill = Skill.objects.get(name__iexact=skill_name)
                except Skill.DoesNotExist:
                    missing_skills.append((resource.title, skill_name))
                    self.stderr.write(
                        f"WARNING: skill '{skill_name}' not found, "
                        f"skipping it for '{resource.title}'"
                    )
                    continue

                _, link_created = ResourceSkill.objects.update_or_create(
                    resource=resource,
                    skill=skill,
                    defaults={
                        "is_primary": is_primary,
                        "coverage": coverage,
                    },
                )
                if link_created:
                    skill_links += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_resources} new resource(s) and "
                f"{skill_links} new skill link(s)."
            )
        )
        if missing_skills:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(missing_skills)} skill link(s) skipped - the skill "
                    f"does not exist in the Skill table yet."
                )
            )
