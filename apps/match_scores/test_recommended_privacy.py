"""
Recommended candidates respect a seeker's search visibility.

Regression: the list ignored `is_open_to_opportunities`, private profiles
and the visibility end date, so a seeker who had hidden themselves from
recruiter search was still put in front of recruiters here.
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.jobs.models import Job
from apps.match_scores.models import MatchScore
from apps.match_scores.services import RecommendationService
from apps.recruiters.models import Company, RecruiterProfile
from apps.seekers.models import SeekerProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def job(django_user_model):
    owner = django_user_model.objects.create_user(
        email="rec-owner@example.com", password="pw-12345678", role="recruiter"
    )
    company = Company.objects.create(name="Priv Co", created_by=owner)
    profile, _ = RecruiterProfile.objects.get_or_create(user=owner)
    profile.company = company
    profile.save()
    return Job.objects.create(
        title="Backend",
        description="Role",
        company=company,
        posted_by=profile,
        status=Job.Status.DRAFT,
        activated_at=timezone.now(),
    )


def candidate(django_user_model, email, score, job, **profile_fields):
    user = django_user_model.objects.create_user(
        email=email, password="pw-12345678", role="seeker", is_email_verified=True
    )
    SeekerProfile.objects.filter(pk=user.seeker_profile.pk).update(
        full_name=email.split("@")[0], **profile_fields
    )
    MatchScore.objects.update_or_create(
        seeker=user.seeker_profile,
        job=job,
        defaults=dict(
            overall_score=score,
            skills_score=score,
            experience_score=50,
            location_score=50,
            salary_score=50,
        ),
    )
    return user.seeker_profile


def names(job):
    return [m.seeker.full_name for m in RecommendationService.top_candidates_for_job(job)]


def test_hidden_seekers_are_not_recommended(django_user_model, job):
    candidate(django_user_model, "visible@example.com", 90, job)
    candidate(django_user_model, "optedout@example.com", 95, job, is_open_to_opportunities=False)
    candidate(
        django_user_model,
        "private@example.com",
        94,
        job,
        visibility=SeekerProfile.Visibility.PRIVATE,
    )
    candidate(
        django_user_model,
        "lapsed@example.com",
        93,
        job,
        searchable_until_date=date.today() - timedelta(days=1),
    )

    assert names(job) == ["visible"]


def test_a_visibility_window_still_open_counts(django_user_model, job):
    candidate(
        django_user_model,
        "until@example.com",
        80,
        job,
        searchable_until_date=date.today() + timedelta(days=3),
    )
    assert names(job) == ["until"]
