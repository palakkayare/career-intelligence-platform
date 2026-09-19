"""
What the recruiter's application screens carry.

Regressions:
  - "Full profile" linked with the account's public id, which the candidate
    endpoints (keyed on SeekerProfile.public_id) could never resolve;
  - the recruiter's timeline showed the candidate's email address.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationStatusHistory
from apps.applications.services import ApplicationStatusService
from apps.jobs.models import Job
from apps.recruiters.models import Company, RecruiterProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def recruiter(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@rec.test", password="pw-12345678", role="recruiter"
    )
    company = Company.objects.create(name="Rec Co", created_by=user)
    profile, _ = RecruiterProfile.objects.get_or_create(user=user)
    profile.company = company
    profile.save()
    return profile


@pytest.fixture
def application(recruiter, django_user_model):
    seeker = django_user_model.objects.create_user(
        email="candidate@rec.test", password="pw-12345678", role="seeker", is_email_verified=True
    )
    job = Job.objects.create(
        title="Backend",
        description="Role",
        company=recruiter.company,
        posted_by=recruiter,
        status=Job.Status.ACTIVE,
        activated_at=timezone.now(),
    )
    app = Application.objects.create(seeker=seeker.seeker_profile, job=job)
    ApplicationStatusHistory.objects.create(
        application=app,
        from_status="",
        to_status="submitted",
        changed_by=seeker,
        notes="Initial application",
    )
    ApplicationStatusService.update_status(
        app, new_status="reviewing", actor=recruiter.user, notes="Looks good"
    )
    return app


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_seeker_block_carries_the_id_the_candidate_api_uses(recruiter, application):
    body = client_for(recruiter.user).get(f"/api/v1/applications/{application.id}/").json()

    seeker = body["seeker"]
    assert seeker["profile_public_id"] == str(application.seeker.public_id)
    assert seeker["public_id"] == str(application.seeker.user.public_id)
    assert seeker["profile_public_id"] != seeker["public_id"]


def test_recruiter_timeline_names_the_actor_in_plain_words(recruiter, application):
    rows = client_for(recruiter.user).get(f"/api/v1/applications/{application.id}/history/").json()

    assert [r["actor"] for r in rows] == ["candidate", "employer"]
    # the recruiter's own note is still theirs to read
    assert rows[-1]["notes"] == "Looks good"
