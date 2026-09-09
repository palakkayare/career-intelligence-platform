"""
Company team seats.

Plan.max_team_members has existed since Phase 2 (FREE 1, BUSINESS 5) but
nothing read it, so a free company could collect any number of recruiters.
The limit is read from whoever created the company, since that is the person
holding the paid seat the rest of the team sits under.
"""
from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.payments.models import Plan, Subscription
from apps.recruiters.models import Company, RecruiterProfile
from apps.recruiters.services import CompanyTeamService

pytestmark = pytest.mark.django_db


@pytest.fixture
def business_plan(plans):
    return Plan.objects.create(
        name='Business Monthly',
        slug='business_monthly',
        tier=Plan.Tier.BUSINESS,
        billing_period=Plan.BillingPeriod.MONTHLY,
        price_inr=Decimal('2999'),
        max_team_members=5,
        sort_order=3,
    )


def make_recruiter(email, company=None):
    user = User.objects.create_user(
        email=email, password='TestPass123!',
        role=User.Role.RECRUITER, is_email_verified=True,
    )
    profile = user.recruiter_profile
    if company is not None:
        profile.company = company
        profile.save(update_fields=['company'])
    return profile


def put_on_plan(user, plan):
    """
    Put a user on a plan.

    Creates the subscription rather than assuming one exists: the signup
    trial is only granted when plans are already in the database, and
    fixture ordering does not guarantee that.
    """
    from datetime import timedelta

    from django.utils import timezone

    now = timezone.now()
    sub = user.subscriptions.order_by('-created_at').first()

    if sub is None:
        return Subscription.objects.create(
            user=user, plan=plan,
            status=Subscription.Status.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )

    sub.plan = plan
    sub.status = Subscription.Status.ACTIVE
    sub.trial_ends_at = None
    sub.current_period_start = now
    sub.current_period_end = now + timedelta(days=30)
    sub.save()
    return sub

def fill_team(company, count, start=0):
    for index in range(start, start + count):
        make_recruiter(f'member{index}@test.com', company=company)


# --------------------------------------------------------------------------
# Reading the limit
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_a_free_company_gets_a_single_seat(company, plans):
    """
    Regression: nothing enforced max_team_members, so a free company could
    add unlimited recruiters.
    """
    assert CompanyTeamService.team_limit(company) == 1


def test_a_business_company_gets_five_seats(company, business_plan):
    put_on_plan(company.created_by, business_plan)

    assert CompanyTeamService.team_limit(company) == 5


def test_an_unlimited_plan_reports_no_limit(company, plans):
    unlimited = Plan.objects.create(
        name='Enterprise', slug='enterprise', tier=Plan.Tier.BUSINESS,
        price_inr=Decimal('9999'), max_team_members=None,
    )
    put_on_plan(company.created_by, unlimited)

    assert CompanyTeamService.team_limit(company) is None


def test_the_creator_is_always_on_file(company):
    """
    created_by is NOT NULL, so the fallback in team_limit() is defensive
    rather than a real path. This pins the constraint that makes it so - if
    the field ever becomes nullable, the fallback stops being theoretical.
    """
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Company.objects.filter(pk=company.pk).update(created_by=None)

# --------------------------------------------------------------------------
# Counting and enforcing
# --------------------------------------------------------------------------

def test_the_current_size_counts_members(company, recruiter, plans):
    assert CompanyTeamService.current_size(company) == 0

    fill_team(company, 3)

    assert CompanyTeamService.current_size(company) == 3


def test_a_company_below_its_limit_can_add(company, business_plan):
    put_on_plan(company.created_by, business_plan)
    fill_team(company, 2)

    assert CompanyTeamService.check_can_add(company) == 5


@pytest.mark.regression
def test_a_full_company_is_refused(company, business_plan):
    put_on_plan(company.created_by, business_plan)
    fill_team(company, 5)

    with pytest.raises(ValidationError):
        CompanyTeamService.check_can_add(company)


def test_the_free_seat_is_used_by_the_first_member(company, plans):
    fill_team(company, 1)

    with pytest.raises(ValidationError):
        CompanyTeamService.check_can_add(company)


def test_an_unlimited_plan_never_refuses(company, plans):
    unlimited = Plan.objects.create(
        name='Enterprise', slug='enterprise', tier=Plan.Tier.BUSINESS,
        price_inr=Decimal('9999'), max_team_members=None,
    )
    put_on_plan(company.created_by, unlimited)
    fill_team(company, 20)

    assert CompanyTeamService.check_can_add(company) is None


def test_the_refusal_says_what_to_do_about_it(company, business_plan):
    put_on_plan(company.created_by, business_plan)
    fill_team(company, 5)

    with pytest.raises(ValidationError) as error:
        CompanyTeamService.check_can_add(company)

    message = str(error.value)
    assert company.name in message
    assert 'upgrade' in message.lower()


@pytest.mark.regression
def test_downgrading_does_not_evict_anyone(company, business_plan, plans):
    """
    Five recruiters on a Business plan that lapses to free are over the new
    limit. Blocking further joins is right; throwing people out of a company
    they already belong to is not.
    """
    put_on_plan(company.created_by, business_plan)
    fill_team(company, 5)

    put_on_plan(company.created_by, plans['free'])

    assert CompanyTeamService.current_size(company) == 5
    with pytest.raises(ValidationError):
        CompanyTeamService.check_can_add(company)


# --------------------------------------------------------------------------
# Through the endpoint
# --------------------------------------------------------------------------

def test_joining_a_full_company_returns_400(company, plans):
    from rest_framework.test import APIClient

    fill_team(company, 1)
    outsider = make_recruiter('outsider@test.com')

    client = APIClient()
    client.force_authenticate(user=outsider.user)
    response = client.post(f'/api/v1/companies/{company.pk}/join/')

    outsider.refresh_from_db()
    assert response.status_code == 400
    assert outsider.company_id is None


def test_joining_a_company_with_room_succeeds(company, business_plan):
    from rest_framework.test import APIClient

    put_on_plan(company.created_by, business_plan)
    joiner = make_recruiter('joiner@test.com')

    client = APIClient()
    client.force_authenticate(user=joiner.user)
    response = client.post(f'/api/v1/companies/{company.pk}/join/')

    joiner.refresh_from_db()
    assert response.status_code == 200
    assert joiner.company_id == company.pk
    assert joiner.is_company_admin is False