"""
Shared fixtures.

A note on signals: creating a User fires post_save handlers that build the
matching SeekerProfile / RecruiterProfile and grant a 7-day Pro trial. The
fixtures below rely on that rather than creating those rows by hand, so the
tests exercise the same path a real signup takes.

Because of the trial, a freshly created seeker is NOT on the free plan. Use
the `free_seeker` fixture when a test needs free-tier limits to apply.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.industries.models import Industry
from apps.jobs.models import Job
from apps.payments.models import Plan
from apps.recruiters.models import Company
from apps.skills.models import Skill


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------

@pytest.fixture
def plans(db):
    """
    The two plans the tests care about, with quotas matching the blueprint:
    free gets 5 applications a month and no AI analysis, pro gets unlimited
    applications and the full analysis suite.
    """
    free = Plan.objects.create(
        name='Free',
        slug='free',
        tier=Plan.Tier.FREE,
        price_inr=Decimal('0'),
        max_applications_per_month=5,
        max_resumes=1,
        max_active_jobs=1,
        max_applicants_view_per_job=10,
        has_resume_ai_analysis=False,
        has_match_score=False,
        sort_order=1,
    )
    pro = Plan.objects.create(
        name='Pro Monthly',
        slug='pro_monthly',
        tier=Plan.Tier.PRO,
        billing_period=Plan.BillingPeriod.MONTHLY,
        price_inr=Decimal('499'),
        max_applications_per_month=None,   # unlimited
        max_resumes=5,
        has_resume_ai_analysis=True,
        has_match_score=True,
        sort_order=2,
    )
    return {'free': free, 'pro': pro}


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------

@pytest.fixture
def seeker_user(db, plans):
    """A verified seeker. Signals give them a profile and a 7-day Pro trial."""
    return User.objects.create_user(
        email='seeker@test.com',
        password='TestPass123!',
        role=User.Role.SEEKER,
        is_email_verified=True,
    )


@pytest.fixture
def seeker(seeker_user):
    return seeker_user.seeker_profile


@pytest.fixture
def free_seeker(seeker_user):
    """
    A seeker whose trial has expired, so FeatureGateService falls back to the
    free plan. Most quota and gating tests need this rather than `seeker`.
    """
    sub = seeker_user.subscriptions.order_by('-created_at').first()
    if sub:
        sub.trial_ends_at = timezone.now() - timedelta(days=1)
        sub.save()
    return seeker_user.seeker_profile


@pytest.fixture
def recruiter_user(db, plans):
    return User.objects.create_user(
        email='recruiter@test.com',
        password='TestPass123!',
        role=User.Role.RECRUITER,
        is_email_verified=True,
    )


@pytest.fixture
def recruiter(recruiter_user):
    return recruiter_user.recruiter_profile


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------

@pytest.fixture
def industry(db):
    return Industry.objects.create(name='Information Technology')


@pytest.fixture
def company(db, recruiter_user, industry):
    return Company.objects.create(
        name='Test Corp',
        industry=industry,
        created_by=recruiter_user,
    )


@pytest.fixture
def skill(db):
    return Skill.objects.create(name='Python')


@pytest.fixture
def make_job(db, company, recruiter, skill):
    """Factory for active job postings. Call it as many times as needed."""
    def _make(title='Backend Developer', **kwargs):
        job = Job.objects.create(
            title=title,
            description='We are hiring a backend developer.',
            company=company,
            posted_by=recruiter,
            status=kwargs.pop('status', Job.Status.ACTIVE),
            activated_at=timezone.now(),
            **kwargs,
        )
        job.required_skills.add(skill)
        return job
    return _make


@pytest.fixture
def job(make_job):
    return make_job()


@pytest.fixture
def six_jobs(make_job):
    """Six active jobs — one more than the free-tier limit of five."""
    return [make_job(title=f'Developer {i}') for i in range(6)]
