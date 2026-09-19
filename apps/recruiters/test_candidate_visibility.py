"""
Who a recruiter may open on /candidates/<public_id>/.

Search stays opt-in, but a seeker who applied to this recruiter's job is
visible to them: they sent their name, resume and cover letter to this
employer themselves, and the application screen already shows it.
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.jobs.models import Job
from apps.payments.models import Plan, Subscription
from apps.recruiters.models import Company, RecruiterProfile
from apps.seekers.models import Education, SeekerProfile, WorkExperience

pytestmark = pytest.mark.django_db


def business_recruiter(django_user_model, email, company_name):
    user = django_user_model.objects.create_user(
        email=email, password="pw-12345678", role="recruiter"
    )
    company = Company.objects.create(name=company_name, created_by=user)
    profile, _ = RecruiterProfile.objects.get_or_create(user=user)
    profile.company = company
    profile.save()
    plan, _ = Plan.objects.get_or_create(
        slug="business-vis",
        defaults=dict(name="Business", tier="business", price_inr=2999, has_candidate_search=True),
    )
    now = timezone.now()
    Subscription.objects.create(
        user=user,
        plan=plan,
        status="active",
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=20),
    )
    return profile


@pytest.fixture
def recruiter(django_user_model):
    return business_recruiter(django_user_model, "vis-owner@rec.test", "Vis Co")


@pytest.fixture
def hidden_seeker(django_user_model):
    user = django_user_model.objects.create_user(
        email="hidden@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )
    SeekerProfile.objects.filter(pk=user.seeker_profile.pk).update(
        full_name="Hidden Person", is_open_to_opportunities=False
    )
    user.seeker_profile.refresh_from_db()
    return user.seeker_profile


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def url(seeker):
    return f"/api/v1/candidates/{seeker.public_id}/"


def apply_to(recruiter, seeker, title="Backend"):
    job = Job.objects.create(
        title=title,
        description="Role",
        company=recruiter.company,
        posted_by=recruiter,
        status=Job.Status.ACTIVE,
        activated_at=timezone.now(),
    )
    return Application.objects.create(seeker=seeker, job=job)


def test_a_hidden_seeker_is_not_browsable(recruiter, hidden_seeker):
    assert client_for(recruiter.user).get(url(hidden_seeker)).status_code == 404


def test_but_is_visible_to_a_recruiter_they_applied_to(recruiter, hidden_seeker):
    apply_to(recruiter, hidden_seeker)
    response = client_for(recruiter.user).get(url(hidden_seeker))
    assert response.status_code == 200
    assert response.json()["current_title"] == hidden_seeker.current_title


def test_another_recruiter_still_cannot_open_them(django_user_model, recruiter, hidden_seeker):
    apply_to(recruiter, hidden_seeker)
    rival = business_recruiter(django_user_model, "rival-vis@rec.test", "Rival Co")
    assert client_for(rival.user).get(url(hidden_seeker)).status_code == 404


def test_a_withdrawn_application_still_counts(recruiter, hidden_seeker):
    application = apply_to(recruiter, hidden_seeker)
    application.soft_delete()  # withdrawn: the recruiter still has the record
    assert client_for(recruiter.user).get(url(hidden_seeker)).status_code == 200


def test_an_applicants_name_and_contact_cost_no_credit(recruiter, hidden_seeker):
    """
    The candidate sent their name, email and resume with the application, so
    masking them here and charging a credit to undo it makes no sense.
    """
    apply_to(recruiter, hidden_seeker)

    body = client_for(recruiter.user).get(url(hidden_seeker)).json()

    assert body["contact_revealed"] is True
    assert body["full_name_masked"] == "Hidden Person"
    assert body["contact"]["email"] == hidden_seeker.user.email


def test_revealing_an_applicant_spends_nothing(recruiter, hidden_seeker):
    from apps.recruiters.models import RecruiterCredits

    apply_to(recruiter, hidden_seeker)
    credits, _ = RecruiterCredits.objects.get_or_create(recruiter=recruiter)
    before = credits.remaining

    response = client_for(recruiter.user).post(
        f"/api/v1/candidates/{hidden_seeker.public_id}/reveal/"
    )

    assert response.status_code == 200, response.content
    assert response.json()["already_revealed"] is True
    credits.refresh_from_db()
    assert credits.remaining == before


def test_a_stranger_is_still_masked_until_a_credit_is_spent(django_user_model, recruiter):
    user = django_user_model.objects.create_user(
        email="stranger@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )
    SeekerProfile.objects.filter(pk=user.seeker_profile.pk).update(
        full_name="Stranger Person", is_open_to_opportunities=True
    )

    body = client_for(recruiter.user).get(url(user.seeker_profile)).json()

    assert body["contact_revealed"] is False
    assert body["full_name_masked"] != "Stranger Person"
    assert body["contact"] is None


def test_a_discoverable_seeker_needs_no_application(django_user_model, recruiter):
    user = django_user_model.objects.create_user(
        email="open@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )
    SeekerProfile.objects.filter(pk=user.seeker_profile.pk).update(is_open_to_opportunities=True)
    assert client_for(recruiter.user).get(url(user.seeker_profile)).status_code == 200


# ── the profile carries a work history ────────────────────────────────


def with_history(seeker, hide_current=False):
    SeekerProfile.objects.filter(pk=seeker.pk).update(hide_current_company=hide_current)
    seeker.refresh_from_db()
    WorkExperience.objects.create(
        seeker=seeker,
        company_name="Acme Corp",
        job_title="Backend Developer",
        start_date=date(2023, 1, 1),
        is_current=True,
    )
    WorkExperience.objects.create(
        seeker=seeker,
        company_name="Old Co",
        job_title="Junior Developer",
        start_date=date(2020, 1, 1),
        end_date=date(2022, 12, 31),
    )
    Education.objects.create(
        seeker=seeker,
        institution_name="IIT",
        degree="btech",
        field_of_study="CS",
        start_year=2016,
        end_year=2020,
    )
    return seeker


def test_profile_includes_work_history_and_education(recruiter, django_user_model):
    """
    Regression: the page had Experience, Education and Resume tabs, but the
    endpoint sent none of it, so every candidate looked empty.
    """
    user = django_user_model.objects.create_user(
        email="withcv@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )
    SeekerProfile.objects.filter(pk=user.seeker_profile.pk).update(is_open_to_opportunities=True)
    seeker = with_history(user.seeker_profile)

    body = client_for(recruiter.user).get(url(seeker)).json()

    assert [e["job_title"] for e in body["experiences"]] == [
        "Backend Developer",
        "Junior Developer",
    ]
    assert body["experiences"][0]["company_name"] == "Acme Corp"
    assert body["educations"][0]["institution_name"] == "IIT"
    assert body["application_id"] is None


def test_a_stealth_seeker_keeps_their_current_employer_hidden(recruiter, django_user_model):
    user = django_user_model.objects.create_user(
        email="stealth@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )
    SeekerProfile.objects.filter(pk=user.seeker_profile.pk).update(is_open_to_opportunities=True)
    seeker = with_history(user.seeker_profile, hide_current=True)

    body = client_for(recruiter.user).get(url(seeker)).json()

    assert body["experiences"][0]["company_name"] == "Stealth"
    assert body["experiences"][1]["company_name"] == "Old Co"  # past employers are not secret


def test_an_applicant_profile_links_back_to_their_application(recruiter, hidden_seeker):
    application = apply_to(recruiter, hidden_seeker)
    body = client_for(recruiter.user).get(url(hidden_seeker)).json()
    assert body["application_id"] == application.id


def test_saved_candidates_carry_the_recruiter_facing_id(recruiter, hidden_seeker):
    """
    Regression: the shortlist linked to the seeker's public profile, which a
    seeker can keep private - a recruiter clicking their own saved candidate
    got "This profile is private".
    """
    from apps.match_scores.models import SavedCandidate
    from apps.match_scores.serializers import SavedCandidateSerializer

    saved = SavedCandidate.objects.create(
        recruiter=recruiter, seeker=hidden_seeker, notes="Call back"
    )
    info = SavedCandidateSerializer(saved).data["seeker_info"]

    assert info["profile_public_id"] == str(hidden_seeker.public_id)
    assert info["public_id"] == str(hidden_seeker.user.public_id)
    assert info["full_name"] == "Hidden Person"
