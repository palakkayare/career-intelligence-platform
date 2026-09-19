"""
The approval queue carries what an approver has to read.

Regression: the queue used the compact list serializer, so the job's
description never reached the screen - the admin's "Read posting" showed
"No description given" for every job.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jobs.models import Job
from apps.recruiters.models import Company, RecruiterProfile

pytestmark = pytest.mark.django_db
URL = "/api/v1/admin/jobs/pending/"

DESCRIPTION = "We need someone to own our billing service end to end, including on-call."


@pytest.fixture
def pending_job(django_user_model):
    owner = django_user_model.objects.create_user(
        email="poster@queue.test", password="pw-12345678", role="recruiter"
    )
    company = Company.objects.create(name="Queue Co", created_by=owner)
    profile, _ = RecruiterProfile.objects.get_or_create(user=owner)
    profile.company = company
    profile.save()
    return Job.objects.create(
        title="Billing Engineer",
        description=DESCRIPTION,
        company=company,
        posted_by=profile,
        status=Job.Status.PENDING_APPROVAL,
        submitted_at=timezone.now(),
    )


def test_the_queue_carries_the_posting_itself(django_user_model, pending_job):
    admin = django_user_model.objects.create_user(
        email="queue-admin@test.com", password="pw-12345678", role="admin"
    )
    client = APIClient()
    client.force_authenticate(admin)

    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    rows = body["results"] if isinstance(body, dict) else body

    assert len(rows) == 1
    assert rows[0]["description"] == DESCRIPTION
    assert rows[0]["submitted_at"] is not None
    assert rows[0]["title"] == "Billing Engineer"
