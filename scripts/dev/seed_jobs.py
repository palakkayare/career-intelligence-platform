"""
Seed a handful of varied ACTIVE jobs so the search page has something to work
with — different locations, salaries, work arrangements and skills.

Run from the project root:

    python manage.py shell < scripts/dev/seed_jobs.py

Development only - never against production.

Safe to re-run: jobs are matched by title and updated instead of duplicated.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.jobs.models import Job, JobCategory
from apps.skills.models import Skill

User = get_user_model()

RECRUITER_EMAIL = "recruiter2@test.com"


def get_skills(*names):
    """Look skills up by name, ignoring any that don't exist in this database."""
    found = list(Skill.objects.filter(name__in=names))
    missing = set(names) - {s.name for s in found}
    if missing:
        print(f"  note: skills not found, skipping — {', '.join(sorted(missing))}")
    return found


def get_category(name):
    return JobCategory.objects.filter(name__iexact=name).first()


JOBS = [
    {
        "title": "Frontend Developer",
        "category": "Frontend Development",
        "location": "Remote",
        "work_arrangement": "remote",
        "employment_type": "full_time",
        "salary_min": 800000,
        "salary_max": 1200000,
        "min_experience_years": 2,
        "max_experience_years": 5,
        "skills": ["JavaScript", "React", "HTML", "CSS", "Git"],
        "description": (
            "We are hiring a Frontend Developer to build and maintain the customer "
            "facing side of our product.\n\n"
            "Responsibilities:\n"
            "- Build accessible, responsive interfaces in React\n"
            "- Turn design files into production components with a shared design system\n"
            "- Write component tests and keep the bundle size in check\n"
            "- Work with backend engineers on API contracts before implementation\n\n"
            "Tech stack: JavaScript, React, Vite, CSS Modules, Playwright."
        ),
    },
    {
        "title": "Senior Python Developer",
        "category": "Backend Development",
        "location": "Bangalore, Karnataka",
        "work_arrangement": "hybrid",
        "employment_type": "full_time",
        "salary_min": 1500000,
        "salary_max": 2500000,
        "min_experience_years": 5,
        "max_experience_years": 9,
        "skills": ["Python", "Django", "PostgreSQL", "Redis", "Docker"],
        "description": (
            "Senior Python Developer to own core backend services as we scale past "
            "our first million requests a day.\n\n"
            "Responsibilities:\n"
            "- Design and own database schemas, migrations and query performance\n"
            "- Build versioned REST APIs with authentication and rate limiting\n"
            "- Set up caching with Redis and background jobs with Celery\n"
            "- Mentor two junior engineers and review their pull requests\n\n"
            "Tech stack: Python, Django, Django REST Framework, PostgreSQL, Redis."
        ),
    },
    {
        "title": "DevOps Engineer",
        "category": "DevOps & Cloud",
        "location": "Pune, Maharashtra",
        "work_arrangement": "hybrid",
        "employment_type": "full_time",
        "salary_min": 2000000,
        "salary_max": 3000000,
        "min_experience_years": 4,
        "max_experience_years": 8,
        "skills": ["Docker", "Kubernetes", "AWS", "CI/CD", "Linux"],
        "description": (
            "DevOps Engineer to run the infrastructure our engineering team ships on "
            "every day.\n\n"
            "Responsibilities:\n"
            "- Own our Kubernetes clusters, from autoscaling to cost control\n"
            "- Build CI/CD pipelines that keep deploys boring and reversible\n"
            "- Set up monitoring, alerting and on-call runbooks\n"
            "- Harden our AWS accounts and manage infrastructure as code\n\n"
            "Tech stack: Docker, Kubernetes, AWS, Terraform, GitHub Actions."
        ),
    },
    {
        "title": "Data Analyst",
        "category": "Data Analyst",
        "location": "Mumbai, Maharashtra",
        "work_arrangement": "on_site",
        "employment_type": "full_time",
        "salary_min": 600000,
        "salary_max": 1000000,
        "min_experience_years": 1,
        "max_experience_years": 4,
        "skills": ["SQL", "Python", "Excel", "Tableau"],
        "description": (
            "Data Analyst to turn our product and revenue data into decisions the "
            "leadership team can act on.\n\n"
            "Responsibilities:\n"
            "- Build and maintain dashboards for product, sales and support\n"
            "- Write SQL against our warehouse and document the models you create\n"
            "- Run analyses on retention, funnel drop-off and pricing experiments\n"
            "- Present findings to non-technical stakeholders every month\n\n"
            "Tools: SQL, Python, dbt, Tableau."
        ),
    },
    {
        "title": "React Native Developer (Contract)",
        "category": "Mobile Development",
        "location": "Remote",
        "work_arrangement": "remote",
        "employment_type": "contract",
        "salary_min": 1000000,
        "salary_max": 1600000,
        "min_experience_years": 3,
        "max_experience_years": 6,
        "skills": ["JavaScript", "React", "Git"],
        "description": (
            "Six month contract to ship the first version of our mobile app on iOS "
            "and Android.\n\n"
            "Responsibilities:\n"
            "- Build the app in React Native against our existing REST API\n"
            "- Handle offline state, push notifications and deep links\n"
            "- Take both apps through store review and release\n"
            "- Hand over with documentation the in-house team can pick up\n\n"
            "Tech stack: React Native, Expo, TypeScript."
        ),
    },
    {
        "title": "Junior Backend Developer (Internship)",
        "category": "Backend Development",
        "location": "Indore, Madhya Pradesh",
        "work_arrangement": "on_site",
        "employment_type": "internship",
        "salary_min": 300000,
        "salary_max": 500000,
        "min_experience_years": 0,
        "max_experience_years": 2,
        "skills": ["Python", "Django", "SQL", "Git"],
        "description": (
            "Six month internship for someone early in their backend career, with a "
            "full time offer for interns who do well.\n\n"
            "What you will do:\n"
            "- Ship small, well tested features to our Django codebase\n"
            "- Pair with a senior engineer twice a week\n"
            "- Write and maintain API documentation\n"
            "- Learn how code gets from a branch to production here\n\n"
            "Tech stack: Python, Django, PostgreSQL, Git."
        ),
    },
]


def run():
    user = User.objects.filter(email=RECRUITER_EMAIL).first()
    if not user:
        print(f"No user with email {RECRUITER_EMAIL}. Edit RECRUITER_EMAIL and re-run.")
        return

    recruiter = getattr(user, "recruiter_profile", None)
    if not recruiter or not recruiter.company_id:
        print("That user has no recruiter profile with a company attached.")
        return

    now = timezone.now()
    print(f"Seeding jobs for {recruiter.company.name}…\n")

    for spec in JOBS:
        print(f"- {spec['title']}")

        job, created = Job.objects.update_or_create(
            title=spec["title"],
            posted_by=recruiter,
            defaults={
                "description": spec["description"],
                "company": recruiter.company,
                "category": get_category(spec["category"]),
                "location": spec["location"],
                "employment_type": spec["employment_type"],
                "work_arrangement": spec["work_arrangement"],
                "salary_min": spec["salary_min"],
                "salary_max": spec["salary_max"],
                "salary_currency": "INR",
                "salary_period": "yearly",
                "is_salary_visible": True,
                "is_salary_negotiable": False,
                "min_experience_years": spec["min_experience_years"],
                "max_experience_years": spec["max_experience_years"],
                "application_deadline": now + timedelta(days=45),
                "status": Job.Status.ACTIVE,
                "activated_at": now,
                "is_deleted": False,
            },
        )

        if hasattr(job, "submitted_at"):
            job.submitted_at = now
            job.save(update_fields=["submitted_at"])

        job.required_skills.set(get_skills(*spec["skills"]))

        if get_category(spec["category"]) is None:
            print(f"  note: category '{spec['category']}' not found, left blank")

        print(f"  {'created' if created else 'updated'}\n")

    print(
        f"Done. Active jobs in database: {Job.objects.filter(status=Job.Status.ACTIVE, is_deleted=False).count()}"
    )


run()
