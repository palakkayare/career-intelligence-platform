"""
The candidate's answer to an offer.

Before this, "offered" was the end of the road inside the product: the real
decision happened over email, and the recruiter's funnel counted offers made
as if every one of them had been taken.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.jobs.models import Job
from apps.notifications.models import Notification
from apps.recruiters.models import Company, RecruiterProfile

pytestmark = pytest.mark.django_db

ANSWER = "/api/v1/applications/me/{}/offer/{}/"
WITHDRAW = "/api/v1/applications/me/{}/withdraw/"


@pytest.fixture
def offer(django_user_model):
    owner = django_user_model.objects.create_user(
        email="hiring@offer.test", password="pw-12345678", role="recruiter"
    )
    company = Company.objects.create(name="Offer Co", created_by=owner)
    profile, _ = RecruiterProfile.objects.get_or_create(user=owner)
    profile.company = company
    profile.full_name = "Asha Rao"
    profile.save()
    job = Job.objects.create(
        title="Backend Engineer",
        description="Role",
        company=company,
        posted_by=profile,
        status=Job.Status.ACTIVE,
        activated_at=timezone.now(),
    )
    seeker = django_user_model.objects.create_user(
        email="candidate@offer.test", password="pw-12345678", role="seeker", is_email_verified=True
    )
    seeker.seeker_profile.full_name = "Palak Kayare"
    seeker.seeker_profile.save()
    return Application.objects.create(
        seeker=seeker.seeker_profile, job=job, status=Application.Status.OFFERED
    )


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_a_candidate_can_decline_an_offer(offer):
    response = client_for(offer.seeker.user).post(
        ANSWER.format(offer.id, "decline"), {"notes": "Taking another role."}
    )

    assert response.status_code == 200
    offer.refresh_from_db()
    assert offer.status == Application.Status.OFFER_DECLINED
    assert offer.status_history.latest("created_at").notes == "Taking another role."


def test_a_candidate_can_accept_an_offer(offer):
    client_for(offer.seeker.user).post(ANSWER.format(offer.id, "accept"))
    offer.refresh_from_db()
    assert offer.status == Application.Status.OFFER_ACCEPTED


def test_the_recruiter_is_told_and_the_candidate_is_not(offer):
    Notification.objects.all().delete()

    client_for(offer.seeker.user).post(ANSWER.format(offer.id, "decline"))

    recruiter_user = offer.job.posted_by.user
    note = Notification.objects.get(user=recruiter_user)
    assert note.title == "Offer declined"
    assert "Palak Kayare" in note.message
    assert note.link == f"/recruiter/applications/{offer.id}"
    # Telling candidates what they themselves just clicked is noise.
    assert not Notification.objects.filter(user=offer.seeker.user).exists()


def test_only_an_offer_can_be_answered(offer):
    Application.objects.filter(pk=offer.pk).update(status=Application.Status.INTERVIEW)

    response = client_for(offer.seeker.user).post(ANSWER.format(offer.id, "accept"))

    assert response.status_code == 400
    offer.refresh_from_db()
    assert offer.status == Application.Status.INTERVIEW


def test_an_answered_offer_cannot_be_answered_again(offer):
    seeker = offer.seeker.user
    client_for(seeker).post(ANSWER.format(offer.id, "accept"))

    response = client_for(seeker).post(ANSWER.format(offer.id, "decline"))

    assert response.status_code == 400
    offer.refresh_from_db()
    assert offer.status == Application.Status.OFFER_ACCEPTED


def test_the_recruiter_cannot_answer_for_the_candidate(offer):
    response = client_for(offer.job.posted_by.user).post(ANSWER.format(offer.id, "accept"))

    assert response.status_code in (403, 404)
    offer.refresh_from_db()
    assert offer.status == Application.Status.OFFERED


def test_another_candidate_cannot_answer_it(django_user_model, offer):
    stranger = django_user_model.objects.create_user(
        email="stranger@offer.test", password="pw-12345678", role="seeker", is_email_verified=True
    )

    response = client_for(stranger).post(ANSWER.format(offer.id, "accept"))

    assert response.status_code in (403, 404)


def test_withdrawing_from_an_offer_is_still_not_allowed(offer):
    """Withdrawing means "I take my application back"; declining is its own thing."""
    response = client_for(offer.seeker.user).post(WITHDRAW.format(offer.id))

    assert response.status_code == 400
    offer.refresh_from_db()
    assert offer.status == Application.Status.OFFERED
