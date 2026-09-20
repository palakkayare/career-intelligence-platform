"""
Fill an empty database with a demo the product can be shown on.

    python manage.py seed_demo          # create it
    python manage.py seed_demo --wipe   # remove it and create it again

An empty platform demos badly: every screen says "nothing yet", and the parts
worth showing - match scores, recommended candidates, a hiring pipeline,
analytics - need data on both sides of the market before they can say
anything at all.

Everything created here is tagged (companies by name, people by the
@demo.careerintel.in address) so `--wipe` can remove exactly what it made and
nothing a real person has done.

Not for production traffic: passwords are shared and deliberately simple.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.applications.models import Application, ApplicationStatusHistory
from apps.jobs.models import Job, JobCategory
from apps.recruiters.models import Company, RecruiterProfile
from apps.seekers.models import Education, SeekerSkill, WorkExperience
from apps.skills.models import Skill

User = get_user_model()

DEMO_DOMAIN = "demo.careerintel.in"
DEMO_PASSWORD = "DemoPass!2026"

COMPANIES = [
    {
        "name": "Nimbus Systems",
        "description": (
            "Cloud infrastructure for Indian fintech. We run the rails other people build on."
        ),
        "headquarters_location": "Bangalore",
        "size": "medium",
        "website": "https://nimbussystems.example.com",
        "recruiter": ("Asha Rao", "Talent Partner"),
    },
    {
        "name": "Kite Analytics",
        "description": "Decision tooling for logistics teams. Small data team, large datasets.",
        "headquarters_location": "Pune",
        "size": "small",
        "website": "https://kiteanalytics.example.com",
        "recruiter": ("Rohan Mehta", "Head of Engineering"),
    },
    {
        "name": "Lantern Health",
        "description": "Patient records that clinicians actually want to use.",
        "headquarters_location": "Hyderabad",
        "size": "medium",
        "website": "https://lanternhealth.example.com",
        "recruiter": ("Priya Nair", "Recruitment Lead"),
    },
]

# (title, company index, category, experience, salary lakh, arrangement, location,
#  required skills, nice-to-have skills)
JOBS = [
    (
        "Senior Backend Engineer",
        0,
        "Backend Development",
        (4, 8),
        (24, 38),
        "hybrid",
        "Bangalore",
        ["Python", "Django", "PostgreSQL", "Docker", "AWS"],
        ["Kubernetes", "Redis", "Celery"],
        "We look after the services that move money. You will own a domain end to end: "
        "design, build, deploy, and the pager that comes with it. Most of our work is "
        "Python and Postgres, with a slow, deliberate move towards event-driven pieces.",
    ),
    (
        "Platform Engineer",
        0,
        "DevOps",
        (3, 6),
        (20, 32),
        "remote",
        "",
        ["Kubernetes", "Terraform", "AWS", "CI/CD", "Linux"],
        ["Prometheus", "Grafana", "Go"],
        "Our platform team keeps deploys boring. You will work on the build pipeline, "
        "cluster configuration and the observability stack, and you will be measured on "
        "how rarely anyone has to think about them.",
    ),
    (
        "Frontend Engineer",
        0,
        "Frontend Development",
        (2, 5),
        (14, 24),
        "hybrid",
        "Bangalore",
        ["React", "TypeScript", "CSS", "REST APIs"],
        ["Next.js", "Tailwind CSS", "Jest"],
        "You will build the dashboards our customers live in all day. Expect real data, "
        "real edge cases, and strong opinions about loading states.",
    ),
    (
        "Data Engineer",
        1,
        "Data Science",
        (3, 7),
        (18, 30),
        "hybrid",
        "Pune",
        ["Python", "SQL", "Apache Airflow", "Apache Spark"],
        ["dbt", "Snowflake", "Apache Kafka"],
        "Our pipelines feed every dashboard in the product. You will own ingestion, "
        "transformation and the tests that stop bad data reaching a customer.",
    ),
    (
        "Data Scientist",
        1,
        "Data Science",
        (2, 5),
        (16, 28),
        "remote",
        "",
        ["Python", "Machine Learning", "Pandas", "Statistics"],
        ["scikit-learn", "Data Visualization", "A/B Testing"],
        "Forecasting and route optimisation for logistics customers. Half the work is "
        "modelling; the other half is explaining what the model cannot do.",
    ),
    (
        "Full Stack Developer",
        1,
        "Full Stack",
        (2, 6),
        (15, 26),
        "onsite",
        "Pune",
        ["JavaScript", "React", "Node.js", "MongoDB"],
        ["TypeScript", "Express.js", "Docker"],
        "Small team, wide surface. You will move between the API and the interface in the "
        "same week, and nothing is someone else's problem.",
    ),
    (
        "Mobile Engineer (React Native)",
        2,
        "Mobile Development",
        (2, 5),
        (14, 24),
        "hybrid",
        "Hyderabad",
        ["React Native", "JavaScript", "REST APIs"],
        ["TypeScript", "iOS Development", "Android Development"],
        "Our app is used at the bedside, on hospital wifi, by people wearing gloves. "
        "Offline behaviour and accessibility are features, not polish.",
    ),
    (
        "QA Automation Engineer",
        2,
        "Quality Assurance",
        (2, 5),
        (12, 20),
        "hybrid",
        "Hyderabad",
        ["Selenium", "Python", "QA Automation", "REST APIs"],
        ["Playwright", "CI/CD", "Load Testing"],
        "You will own the suite that decides whether a release ships. Healthcare software, "
        "so a flaky test is worse than a slow one.",
    ),
    (
        "Product Designer",
        2,
        "Design",
        (3, 6),
        (16, 26),
        "remote",
        "",
        ["UI Design", "UX Design", "Figma", "Prototyping"],
        ["Design Systems", "User Research", "Accessibility Design"],
        "Clinical software has hard constraints and impatient users. You will do research "
        "in hospitals, then design for the worst five minutes of someone's shift.",
    ),
    (
        "Engineering Manager",
        0,
        "Backend Development",
        (7, 12),
        (35, 55),
        "hybrid",
        "Bangalore",
        ["Leadership", "Mentoring", "System Design", "Agile"],
        ["Python", "Hiring", "Roadmapping"],
        "Two teams, nine engineers. You will spend your time on people, planning and "
        "unblocking, and keep just enough code to stay honest.",
    ),
]

# (name, title, city, years, skills, bio)
CANDIDATES = [
    (
        "Ananya Iyer",
        "Backend Developer",
        "Bangalore",
        4,
        ["Python", "Django", "PostgreSQL", "Docker", "REST APIs", "Git"],
        "Backend developer working on payments infrastructure. I like boring, well-tested code.",
    ),
    (
        "Vikram Shah",
        "DevOps Engineer",
        "Bangalore",
        6,
        ["Kubernetes", "Terraform", "AWS", "Linux", "CI/CD", "Docker", "Prometheus"],
        "Platform engineer. Most of my work is making deployments uneventful.",
    ),
    (
        "Meera Krishnan",
        "Frontend Developer",
        "Pune",
        3,
        ["React", "TypeScript", "CSS", "Redux", "Jest"],
        "Frontend developer who cares about accessibility and fast first paints.",
    ),
    (
        "Arjun Desai",
        "Data Analyst",
        "Pune",
        2,
        ["Python", "SQL", "Pandas", "Data Visualization", "Excel"],
        "Analyst moving towards data engineering. Currently learning Airflow and Spark.",
    ),
    (
        "Sana Qureshi",
        "Full Stack Developer",
        "Hyderabad",
        5,
        ["JavaScript", "React", "Node.js", "MongoDB", "Express.js", "Docker"],
        "Full stack developer in healthtech. Comfortable owning a feature from schema to screen.",
    ),
    (
        "Karthik Reddy",
        "QA Engineer",
        "Hyderabad",
        3,
        ["Selenium", "Python", "QA Automation", "Postman", "Git"],
        "QA engineer building test suites people actually trust.",
    ),
    (
        "Divya Menon",
        "Product Designer",
        "Remote",
        4,
        ["UI Design", "UX Design", "Figma", "User Research", "Prototyping"],
        "Designer with a research habit. I work best where the constraints are real.",
    ),
]

# What a pipeline looks like a few weeks in.
PIPELINE = [
    # (candidate index, job index, status, days ago applied)
    (0, 0, "offered", 21),
    (1, 1, "interview", 14),
    (2, 2, "shortlisted", 9),
    (3, 3, "reviewing", 6),
    (4, 5, "submitted", 3),
    (5, 7, "rejected", 18),
    (6, 8, "offer_accepted", 30),
    (0, 9, "submitted", 2),
    (2, 5, "submitted", 5),
    (4, 6, "reviewing", 8),
]


class Command(BaseCommand):
    help = "Create a demo dataset: companies, jobs, candidates and a live pipeline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wipe",
            action="store_true",
            help="Delete the previous demo data first (only what this command created).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(7)  # same demo every time

        if options["wipe"]:
            self._wipe()

        recruiters = self._companies_and_recruiters()
        jobs = self._jobs(recruiters)
        candidates = self._candidates()
        applications = self._pipeline(candidates, jobs)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready: {len(recruiters)} companies, {len(jobs)} live jobs, "
                f"{len(candidates)} candidates, {applications} applications.\n"
                f"Everyone's password is {DEMO_PASSWORD!r}; "
                f"emails look like ananya.iyer@{DEMO_DOMAIN}."
            )
        )

    # ── helpers ───────────────────────────────────────────────────────

    def _wipe(self):
        """
        Remove what this command made, in the order the database allows.

        Applications are protected against a job disappearing underneath them
        - which is right, a hiring record should outlive a listing - so they
        go first, then the jobs, then the companies (which point at the user
        who created them), and the people last.
        """
        users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")
        companies = Company.all_objects.filter(name__in=[c["name"] for c in COMPANIES])
        jobs = Job.all_objects.filter(company__in=companies)

        Application.all_objects.filter(job__in=jobs).delete()
        Application.all_objects.filter(seeker__user__in=users).delete()
        jobs.delete()

        count = users.count()
        # Companies point at the user who created them, so they go first.
        companies.delete()
        users.delete()
        self.stdout.write(f"Removed {count} demo users, their companies and jobs.")

    def _user(self, name, role):
        email = f"{name.lower().replace(' ', '.')}@{DEMO_DOMAIN}"
        user, created = User.objects.get_or_create(
            email=email, defaults={"role": role, "is_email_verified": True}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.is_email_verified = True
            user.save()
        return user

    def _companies_and_recruiters(self):
        recruiters = []
        for spec in COMPANIES:
            full_name, position = spec["recruiter"]
            user = self._user(full_name, "recruiter")

            company, _ = Company.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "description": spec["description"],
                    "headquarters_location": spec["headquarters_location"],
                    "size": spec["size"],
                    "website": spec["website"],
                    "created_by": user,
                    "is_verified": True,
                    "verified_at": timezone.now(),
                },
            )

            profile, _ = RecruiterProfile.objects.get_or_create(user=user)
            profile.company = company
            profile.is_company_admin = True
            profile.full_name = full_name
            profile.position = position
            profile.save()
            recruiters.append(profile)
        return recruiters

    def _jobs(self, recruiters):
        now = timezone.now()
        created = []

        for idx, (
            title,
            company_idx,
            category_name,
            experience,
            salary_lakh,
            arrangement,
            location,
            required,
            nice,
            description,
        ) in enumerate(JOBS):
            recruiter = recruiters[company_idx]
            category = JobCategory.objects.filter(name__iexact=category_name).first()
            posted_days_ago = 3 + idx * 4

            job, _ = Job.objects.get_or_create(
                title=title,
                company=recruiter.company,
                defaults={
                    "description": description,
                    "posted_by": recruiter,
                    "category": category,
                    "min_experience_years": experience[0],
                    "max_experience_years": experience[1],
                    "employment_type": "full_time",
                    "work_arrangement": arrangement,
                    "location": location,
                    "salary_min": Decimal(salary_lakh[0] * 100000),
                    "salary_max": Decimal(salary_lakh[1] * 100000),
                    "salary_period": "yearly",
                    "is_salary_visible": True,
                    "status": Job.Status.ACTIVE,
                    "submitted_at": now - timedelta(days=posted_days_ago + 1),
                    "approved_at": now - timedelta(days=posted_days_ago),
                    "activated_at": now - timedelta(days=posted_days_ago),
                    "application_deadline": now + timedelta(days=30),
                    "view_count": random.randint(18, 260),
                },
            )
            self._attach(job.required_skills, required)
            self._attach(job.nice_to_have_skills, nice)
            created.append(job)
        return created

    def _candidates(self):
        profiles = []
        for name, title, city, years, skills, bio in CANDIDATES:
            user = self._user(name, "seeker")
            profile = user.seeker_profile
            profile.full_name = name
            profile.current_title = title
            profile.location = city
            profile.years_of_experience = years
            profile.bio = bio
            profile.is_open_to_opportunities = True
            profile.save()

            for skill_name in skills:
                skill = self._skill(skill_name)
                if skill:
                    SeekerSkill.objects.get_or_create(
                        seeker=profile,
                        skill=skill,
                        defaults={
                            "proficiency": random.choice(["intermediate", "advanced"]),
                            "years_of_experience": max(1, years - random.randint(0, 2)),
                        },
                    )

            if not profile.experiences.exists():
                WorkExperience.objects.create(
                    seeker=profile,
                    company_name=random.choice(
                        ["Zeta Labs", "Orbit Retail", "Finwave", "Trailhead"]
                    ),
                    job_title=title,
                    start_date=timezone.localdate() - timedelta(days=365 * years),
                    is_current=True,
                    description=f"{title} working across the product.",
                )
            if not profile.educations.exists():
                Education.objects.create(
                    seeker=profile,
                    institution_name=random.choice(
                        ["IIT Bombay", "NIT Trichy", "VIT Vellore", "BITS Pilani", "IIIT Hyderabad"]
                    ),
                    degree="bachelors",
                    field_of_study="Computer Science",
                    start_year=2015,
                    end_year=2019,
                )
            profiles.append(profile)
        return profiles

    def _pipeline(self, candidates, jobs):
        now = timezone.now()
        made = 0

        for candidate_idx, job_idx, status, days_ago in PIPELINE:
            seeker = candidates[candidate_idx]
            job = jobs[job_idx]
            submitted = now - timedelta(days=days_ago)

            application, created = Application.objects.get_or_create(
                seeker=seeker,
                job=job,
                defaults={
                    "status": status,
                    "cover_letter": (
                        f"I have been working as a {seeker.current_title} for "
                        f"{seeker.years_of_experience} years and this role lines up with "
                        "what I want to do next."
                    ),
                    "submitted_at": submitted,
                    "last_status_change_at": now - timedelta(days=max(0, days_ago - 4)),
                },
            )
            if not created:
                continue

            Application.objects.filter(pk=application.pk).update(submitted_at=submitted)
            self._history(application, status, submitted, now)
            Job.objects.filter(pk=job.pk).update(
                application_count=Application.objects.filter(job=job).count()
            )
            made += 1
        return made

    def _history(self, application, status, submitted, now):
        """A pipeline is only believable with the steps that led to it."""
        route = {
            "submitted": [],
            "reviewing": ["reviewing"],
            "shortlisted": ["reviewing", "shortlisted"],
            "interview": ["reviewing", "shortlisted", "interview"],
            "offered": ["reviewing", "shortlisted", "interview", "offered"],
            "offer_accepted": [
                "reviewing",
                "shortlisted",
                "interview",
                "offered",
                "offer_accepted",
            ],
            "rejected": ["reviewing", "rejected"],
        }[status]

        first = ApplicationStatusHistory.objects.create(
            application=application,
            from_status="",
            to_status="submitted",
            changed_by=application.seeker.user,
        )
        # created_at is auto_now_add, so every row has to be pushed back
        # after the fact - otherwise the first step of the story is stamped
        # today and sorts after the steps that followed it.
        ApplicationStatusHistory.objects.filter(pk=first.pk).update(created_at=submitted)
        previous = "submitted"
        step = max(1, (now - submitted).days // (len(route) + 1))
        for n, to_status in enumerate(route, start=1):
            row = ApplicationStatusHistory.objects.create(
                application=application,
                from_status=previous,
                to_status=to_status,
                changed_by=(
                    application.seeker.user
                    if to_status.startswith("offer_")
                    else application.job.posted_by.user
                ),
            )
            ApplicationStatusHistory.objects.filter(pk=row.pk).update(
                created_at=submitted + timedelta(days=step * n)
            )
            previous = to_status

    @staticmethod
    def _skill(name):
        return (
            Skill.objects.filter(name__iexact=name).first()
            or Skill.objects.filter(aliases__icontains=name.lower()).first()
        )

    def _attach(self, relation, names):
        for name in names:
            skill = self._skill(name)
            if skill:
                relation.add(skill)
