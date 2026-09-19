"""
Joining a company needs an admin's approval.

Before this, any recruiter could put themselves inside any company and read
its jobs, applicants and team straight away.
"""

import pytest
from rest_framework.test import APIClient

from apps.recruiters.models import Company, CompanyJoinRequest, RecruiterProfile

pytestmark = pytest.mark.django_db

JOIN = "/api/v1/companies/{}/join/"
LIST = "/api/v1/companies/join-requests/"
DECIDE = "/api/v1/companies/join-requests/{}/{}/"


def recruiter(django_user_model, email, company=None, admin=False):
    user = django_user_model.objects.create_user(
        email=email, password="pw-12345678", role="recruiter"
    )
    profile, _ = RecruiterProfile.objects.get_or_create(user=user)
    profile.full_name = email.split("@")[0].title()
    profile.company = company
    profile.is_company_admin = admin
    profile.save()
    return profile


def make_company(name, creator, **extra):
    return Company.objects.create(name=name, created_by=creator, **extra)


@pytest.fixture(autouse=True)
def seats():
    """Seat limits are their own feature; give every company room here."""
    from apps.payments.models import Plan

    return Plan.objects.create(name="Free", slug="free-join", tier="free", max_team_members=5)


@pytest.fixture
def owner(django_user_model):
    person = recruiter(django_user_model, "boss@acme.example.com")
    company = make_company("Acme Corp", person.user, website="https://acme.example.com")
    person.company = company
    person.is_company_admin = True
    person.save()
    return person


def client_for(profile):
    c = APIClient()
    c.force_authenticate(profile.user)
    return c


def test_joining_a_staffed_company_only_asks(django_user_model, owner):
    outsider = recruiter(django_user_model, "stranger@other.test")

    response = client_for(outsider).post(JOIN.format(owner.company_id))

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    outsider.refresh_from_db()
    assert outsider.company_id is None  # no access yet


def test_an_admin_sees_and_approves_the_request(django_user_model, owner):
    outsider = recruiter(django_user_model, "stranger@other.test")
    client_for(outsider).post(JOIN.format(owner.company_id))

    listed = client_for(owner).get(LIST).json()
    assert [r["recruiter_email"] for r in listed] == ["stranger@other.test"]

    approved = client_for(owner).post(DECIDE.format(listed[0]["id"], "approve"))

    assert approved.status_code == 200
    outsider.refresh_from_db()
    assert outsider.company_id == owner.company_id
    assert outsider.is_company_admin is False


def test_a_rejected_request_leaves_them_outside(django_user_model, owner):
    outsider = recruiter(django_user_model, "stranger@other.test")
    client_for(outsider).post(JOIN.format(owner.company_id))
    request_id = client_for(owner).get(LIST).json()[0]["id"]

    client_for(owner).post(DECIDE.format(request_id, "reject"))

    outsider.refresh_from_db()
    assert outsider.company_id is None
    assert CompanyJoinRequest.objects.get(pk=request_id).status == "rejected"


def test_a_non_admin_cannot_decide(django_user_model, owner):
    colleague = recruiter(django_user_model, "colleague@acme.example.com", company=owner.company)
    outsider = recruiter(django_user_model, "stranger@other.test")
    client_for(outsider).post(JOIN.format(owner.company_id))
    request_id = CompanyJoinRequest.objects.get().id

    response = client_for(colleague).post(DECIDE.format(request_id, "approve"))

    assert response.status_code == 403
    outsider.refresh_from_db()
    assert outsider.company_id is None


def test_an_admin_of_another_company_cannot_decide(django_user_model, owner):
    rival_admin = recruiter(django_user_model, "rival@rival.test")
    other_company = make_company("Rival Ltd", rival_admin.user)
    rival_admin.company = other_company
    rival_admin.is_company_admin = True
    rival_admin.save()
    outsider = recruiter(django_user_model, "stranger@other.test")
    client_for(outsider).post(JOIN.format(owner.company_id))

    response = client_for(rival_admin).post(
        DECIDE.format(CompanyJoinRequest.objects.get().id, "approve")
    )

    assert response.status_code == 403


def test_a_matching_email_domain_joins_at_once(django_user_model, owner):
    colleague = recruiter(django_user_model, "new.hire@acme.example.com")

    response = client_for(colleague).post(JOIN.format(owner.company_id))

    assert response.json()["status"] == "joined"
    colleague.refresh_from_db()
    assert colleague.company_id == owner.company_id
    assert colleague.is_company_admin is False


def test_an_empty_company_lets_people_in_without_a_wait(django_user_model):
    """Nobody is there to approve, so the request would never be answered."""
    founder = recruiter(django_user_model, "founder@fresh.test")
    empty = make_company("Fresh Start", founder.user)  # created, but nobody has joined it
    person = recruiter(django_user_model, "first@fresh.test")

    response = client_for(person).post(JOIN.format(empty.id))

    assert response.json()["status"] == "joined"
    person.refresh_from_db()
    assert person.company_id == empty.id
    # Whoever arrives first does not get to run the company.
    assert person.is_company_admin is False


def test_the_creator_joining_their_own_company_becomes_its_admin(django_user_model):
    founder = recruiter(django_user_model, "founder@fresh.test")
    company = make_company("Fresh Start", founder.user)

    client_for(founder).post(JOIN.format(company.id))

    founder.refresh_from_db()
    assert founder.company_id == company.id
    assert founder.is_company_admin is True


def test_asking_twice_does_not_pile_up(django_user_model, owner):
    outsider = recruiter(django_user_model, "stranger@other.test")
    client_for(outsider).post(JOIN.format(owner.company_id))
    client_for(outsider).post(JOIN.format(owner.company_id))

    assert CompanyJoinRequest.objects.filter(status="pending").count() == 1
    assert len(client_for(outsider).get(LIST).json()) == 1  # they see their own


def test_someone_already_in_a_company_cannot_ask(django_user_model, owner):
    colleague = recruiter(django_user_model, "colleague@acme.example.com", company=owner.company)
    other = make_company("Rival Ltd", colleague.user)

    response = client_for(colleague).post(JOIN.format(other.id))

    assert response.status_code == 400
