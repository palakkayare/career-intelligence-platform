"""
Who sees what on GET /api/v1/jobs/<uuid>/.

Regression: every signed-in user - any seeker, any other company's
recruiter - got the owner's view, including the posting's view and
application counts and the moderation note.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.jobs.models import Job
from apps.recruiters.models import Company, RecruiterProfile

pytestmark = pytest.mark.django_db

OWNER_ONLY = ("view_count", "application_count", "rejection_reason")


def make_recruiter(django_user_model, email, company_name):
    user = django_user_model.objects.create_user(
        email=email, password="pw-12345678", role="recruiter", is_email_verified=True
    )
    company = Company.objects.create(name=company_name, created_by=user)
    # A profile is created on signup, without a company.
    profile, _ = RecruiterProfile.objects.get_or_create(user=user)
    profile.company = company
    profile.save()
    return profile


@pytest.fixture
def owner(django_user_model):
    return make_recruiter(django_user_model, "owner@detail.test", "Owner Co")


@pytest.fixture
def job(owner):
    return Job.objects.create(
        title="Backend Engineer",
        description="Role",
        company=owner.company,
        posted_by=owner,
        status=Job.Status.ACTIVE,
        activated_at=timezone.now() - timedelta(days=1),
        view_count=41,
        application_count=7,
    )


@pytest.fixture
def seeker(django_user_model):
    return django_user_model.objects.create_user(
        email="reader@detail.test", password="pw-12345678", role="seeker", is_email_verified=True
    )


def get(user, job):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    response = client.get(f"/api/v1/jobs/{job.public_id}/")
    assert response.status_code == 200, response.content
    return response.json()


def test_owner_sees_everything(owner, job):
    body = get(owner.user, job)
    assert body["view_count"] == 41 and body["application_count"] == 7
    assert "rejection_reason" in body and "posted_by_name" in body
    assert "my_application" not in body


def test_seeker_does_not_see_owner_only_fields(seeker, job):
    body = get(seeker, job)
    for field in OWNER_ONLY:
        assert field not in body
    assert "posted_by_name" in body  # unchanged: signed-in readers see who is hiring


def test_another_companys_recruiter_is_just_a_reader(django_user_model, job):
    rival = make_recruiter(django_user_model, "rival@detail.test", "Rival Co")
    body = get(rival.user, job)
    for field in OWNER_ONLY:
        assert field not in body
    assert body["my_application"] is None


def test_admin_sees_everything(django_user_model, job):
    admin = django_user_model.objects.create_user(
        email="admin@detail.test", password="pw-12345678", role="admin", is_email_verified=True
    )
    assert get(admin, job)["application_count"] == 7


def test_anonymous_reader_gets_neither_counters_nor_recruiter(job):
    body = get(None, job)
    for field in OWNER_ONLY + ("posted_by_name", "my_application"):
        assert field not in body


def test_seeker_sees_their_own_live_application(seeker, job):
    assert get(seeker, job)["my_application"] is None

    app = Application.objects.create(seeker=seeker.seeker_profile, job=job, status="shortlisted")
    mine = get(seeker, job)["my_application"]
    assert mine["id"] == app.id and mine["status"] == "shortlisted"


def test_a_withdrawn_application_does_not_block_applying_again(seeker, job):
    app = Application.objects.create(seeker=seeker.seeker_profile, job=job, status="withdrawn")
    app.soft_delete()
    assert get(seeker, job)["my_application"] is None


def test_another_seekers_application_is_not_mine(django_user_model, seeker, job):
    other = django_user_model.objects.create_user(
        email="other@detail.test", password="pw-12345678", role="seeker", is_email_verified=True
    )
    Application.objects.create(seeker=other.seeker_profile, job=job)
    assert get(seeker, job)["my_application"] is None
