"""
Seed subscription plans with quotas and feature flags.

Quota semantics: null (None) means unlimited — the sentinel pattern.
Feature flags default to False on the model, so Free/unlisted plans
automatically have every premium feature turned off.

Safe to re-run: update_or_create matches on slug and updates in place.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.payments.models import Plan

PLANS = [
    {
        "name": "Free",
        "slug": "free",
        "tier": Plan.Tier.FREE,
        "billing_period": None,
        "price_inr": Decimal("0"),
        "features": [
            "5 job applications per month",
            "Basic job search",
            "Profile creation",
            "Browse companies",
        ],
        "sort_order": 1,
        # Quotas — the Free tier is where limits actually bite
        "max_applications_per_month": 5,
        "max_active_jobs": 1,  # recruiters on Free: 1 open job
        "max_applicants_view_per_job": 10,  # see only first 10 applicants
        "max_resumes": 1,
        "max_team_members": 1,
        "max_saved_searches": 3,
    },
    {
        "name": "Pro Monthly",
        "slug": "pro_monthly",
        "tier": Plan.Tier.PRO,
        "billing_period": Plan.BillingPeriod.MONTHLY,
        "price_inr": Decimal("499"),
        "features": [
            "Unlimited job applications",
            "AI resume analysis",
            "Match score breakdown",
            "Skill gap report",
            "Career path engine",
            "Priority in recruiter search",
        ],
        "sort_order": 2,
        # Quotas — None = unlimited
        "max_applications_per_month": None,
        "max_resumes": 5,
        "max_saved_searches": None,
        # Seeker-side feature flags
        "has_match_score": True,
        "has_skill_gap": True,
        "has_career_path": True,
        "has_priority_search_visibility": True,
        "has_resume_ai_analysis": True,
        "has_salary_insights": True,
    },
    {
        "name": "Pro Yearly",
        "slug": "pro_yearly",
        "tier": Plan.Tier.PRO,
        "billing_period": Plan.BillingPeriod.YEARLY,
        "price_inr": Decimal("4790"),  # 20% discount
        "features": [
            "Everything in Pro Monthly",
            "20% savings vs monthly",
            "Annual career roadmap review",
        ],
        "sort_order": 3,
        # Same capabilities as Pro Monthly — only the billing period differs
        "max_applications_per_month": None,
        "max_resumes": 5,
        "max_saved_searches": None,
        "has_match_score": True,
        "has_skill_gap": True,
        "has_career_path": True,
        "has_priority_search_visibility": True,
        "has_resume_ai_analysis": True,
        "has_salary_insights": True,
    },
    {
        "name": "Business Monthly",
        "slug": "business_monthly",
        "tier": Plan.Tier.BUSINESS,
        "billing_period": Plan.BillingPeriod.MONTHLY,
        "price_inr": Decimal("2999"),
        "features": [
            "Unlimited job postings",
            "AI candidate ranking",
            "Advanced filters",
            "Bulk applicant management",
            "Company branding page",
            "Analytics dashboard",
            "Up to 5 team members",
            "Candidate database search",
        ],
        "sort_order": 4,
        # Quotas — recruiter-side limits lift here
        "max_active_jobs": None,  # unlimited open jobs
        "max_applicants_view_per_job": None,  # see every applicant
        "max_team_members": 5,
        # Recruiter-side feature flags
        "has_candidate_search": True,
        "has_advanced_filters": True,
        "has_company_branding": True,
        "has_analytics_dashboard": True,
    },
    {
        "name": "Business Yearly",
        "slug": "business_yearly",
        "tier": Plan.Tier.BUSINESS,
        "billing_period": Plan.BillingPeriod.YEARLY,
        "price_inr": Decimal("28790"),  # 20% discount
        "features": [
            "Everything in Business Monthly",
            "20% savings vs monthly",
            "Dedicated account manager",
        ],
        "sort_order": 5,
        # Same capabilities as Business Monthly
        "max_active_jobs": None,
        "max_applicants_view_per_job": None,
        "max_team_members": 5,
        "has_candidate_search": True,
        "has_advanced_filters": True,
        "has_company_branding": True,
        "has_analytics_dashboard": True,
    },
]


class Command(BaseCommand):
    help = "Seed subscription plans (safe to re-run; updates existing plans in place)"

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for data in PLANS:
            obj, was_created = Plan.objects.update_or_create(
                slug=data["slug"],
                defaults=data,
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Plans seeded: {created} created, {updated} updated " f"(total: {len(PLANS)})."
            )
        )
