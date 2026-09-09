"""
Candidate discovery: search, contact reveals and the credit wallet.

Two things make this worth covering. Credits are money - a recruiter pays
for a Business plan and gets a fixed number of contact unlocks a month, so
an off-by-one either gives away reveals or withholds ones they paid for.
And search decides who is visible to recruiters at all, which is the
privacy promise made to every seeker.
"""
from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.recruiters.candidate_services import (
    CandidateProfileService,
    CandidateSearchService,
)
from apps.recruiters.models import CandidateView, RecruiterCredits
from apps.seekers.models import SeekerProfile

pytestmark = pytest.mark.django_db


def make_seeker(email, **profile_fields):
    """A discoverable seeker: verified, opted in, not private."""
    user = User.objects.create_user(
        email=email, password='TestPass123!',
        role=User.Role.SEEKER, is_email_verified=True,
    )
    profile = user.seeker_profile
    profile.visibility = SeekerProfile.Visibility.RECRUITERS_ONLY
    profile.is_open_to_opportunities = True
    for field, value in profile_fields.items():
        setattr(profile, field, value)
    profile.save()
    return profile


@pytest.fixture
def credits(recruiter):
    """
    The wallet already exists - a signal creates it with the profile - so
    this configures the existing row rather than making a second one.
    """
    wallet = RecruiterCredits.objects.get(recruiter=recruiter)
    wallet.monthly_reveal_limit = 5
    wallet.reveals_used_this_month = 0
    wallet.cycle_starts_on = date.today()
    wallet.save()
    return wallet

def search(recruiter, **filters):
    return CandidateSearchService.search(recruiter, filters)


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_a_discoverable_seeker_is_found(recruiter, plans):
    """Regression: candidate_services.py sat at 28% coverage."""
    make_seeker('found@test.com')

    result = search(recruiter)

    assert result['total'] >= 1


def test_a_private_seeker_is_not_found(recruiter, plans):
    """The visibility fix, checked through the search path itself."""
    profile = make_seeker('private@test.com')
    profile.visibility = SeekerProfile.Visibility.PRIVATE
    profile.save()

    assert search(recruiter)['total'] == 0


def test_an_opted_out_seeker_is_not_found(recruiter, plans):
    profile = make_seeker('optout@test.com')
    profile.is_open_to_opportunities = False
    profile.save()

    assert search(recruiter)['total'] == 0


def test_an_unverified_seeker_is_not_found(recruiter, plans):
    profile = make_seeker('unverified@test.com')
    profile.user.is_email_verified = False
    profile.user.save()

    assert search(recruiter)['total'] == 0


def test_searching_by_city(recruiter, plans):
    make_seeker('blr@test.com', location='Bangalore')
    make_seeker('pune@test.com', location='Pune')

    result = search(recruiter, location_city='bangalore')

    assert result['total'] == 1


def test_searching_by_experience_range(recruiter, plans):
    make_seeker('junior@test.com', years_of_experience=1)
    make_seeker('senior@test.com', years_of_experience=9)

    assert search(recruiter, experience_years_min=5)['total'] == 1
    assert search(recruiter, experience_years_max=3)['total'] == 1


def test_free_text_search_covers_title_and_bio(recruiter, plans):
    make_seeker('be@test.com', current_title='Backend Developer')
    make_seeker('fe@test.com', current_title='Frontend Developer')

    assert search(recruiter, q='Backend')['total'] == 1


def test_results_are_paginated(recruiter, plans):
    for index in range(5):
        make_seeker(f'page{index}@test.com')

    page = CandidateSearchService.search(recruiter, {}, page=1, page_size=2)

    assert page['total'] == 5
    assert len(page['seekers']) == 2
    assert page['has_next'] is True


def test_the_last_page_reports_no_next(recruiter, plans):
    for index in range(3):
        make_seeker(f'last{index}@test.com')

    page = CandidateSearchService.search(recruiter, {}, page=2, page_size=2)

    assert page['has_next'] is False


# --------------------------------------------------------------------------
# Search audit trail
# --------------------------------------------------------------------------

def test_search_results_are_logged(recruiter, plans):
    make_seeker('logged@test.com')

    search(recruiter)

    assert CandidateView.objects.filter(
        recruiter=recruiter, view_kind=CandidateView.ViewKind.SEARCH_RESULT,
    ).exists()


@pytest.mark.regression
def test_repeated_searches_do_not_flood_the_audit_table(recruiter, plans):
    """
    A recruiter typing into a search box fires a request per keystroke. One
    row each would bury the table in noise, so views are deduplicated inside
    a 24-hour window.
    """
    make_seeker('typed@test.com')

    for _ in range(5):
        search(recruiter)

    assert CandidateView.objects.filter(recruiter=recruiter).count() == 1


# --------------------------------------------------------------------------
# Contact reveal
# --------------------------------------------------------------------------

def test_revealing_a_contact_spends_one_credit(recruiter, credits, plans):
    seeker = make_seeker('reveal@test.com')

    result = CandidateProfileService.reveal_contact(recruiter, seeker)

    credits.refresh_from_db()
    assert result['already_revealed'] is False
    assert credits.reveals_used_this_month == 1
    assert result['credits_remaining'] == 4


@pytest.mark.regression
def test_revealing_the_same_seeker_twice_is_free(recruiter, credits, plans):
    """
    Charging again for a contact the recruiter already paid to see would be
    taking money for nothing.
    """
    seeker = make_seeker('twice@test.com')
    CandidateProfileService.reveal_contact(recruiter, seeker)

    result = CandidateProfileService.reveal_contact(recruiter, seeker)

    credits.refresh_from_db()
    assert result['already_revealed'] is True
    assert credits.reveals_used_this_month == 1


@pytest.mark.regression
def test_running_out_of_credits_blocks_the_reveal(recruiter, credits, plans):
    """The wallet is the product. Spending past zero gives away the plan."""
    credits.reveals_used_this_month = 5
    credits.save()
    seeker = make_seeker('blocked@test.com')

    with pytest.raises(PermissionDenied):
        CandidateProfileService.reveal_contact(recruiter, seeker)

    credits.refresh_from_db()
    assert credits.reveals_used_this_month == 5


def test_a_recruiter_with_no_wallet_cannot_reveal(recruiter, plans):
    """
    A signal gives every recruiter a wallet, so this only happens if the row
    is missing - but the service still has to fail cleanly rather than crash.
    """
    RecruiterCredits.objects.filter(recruiter=recruiter).delete()
    seeker = make_seeker('nowallet@test.com')

    with pytest.raises(ValidationError):
        CandidateProfileService.reveal_contact(recruiter, seeker)

def test_a_reveal_notifies_the_seeker(recruiter, credits, plans):
    from apps.notifications.models import Notification

    seeker = make_seeker('notified@test.com')

    CandidateProfileService.reveal_contact(recruiter, seeker)

    assert Notification.objects.filter(user=seeker.user).exists()


def test_a_reveal_is_recorded_against_the_seeker(recruiter, credits, plans):
    seeker = make_seeker('recorded@test.com')

    CandidateProfileService.reveal_contact(recruiter, seeker)

    view = CandidateView.objects.get(
        recruiter=recruiter, seeker=seeker, contact_revealed=True,
    )
    assert view.revealed_at is not None


# --------------------------------------------------------------------------
# Credit cycle
# --------------------------------------------------------------------------

def test_remaining_never_goes_negative(recruiter, credits):
    credits.reveals_used_this_month = 99
    credits.save()

    assert credits.remaining == 0


def test_the_cycle_runs_for_30_days(recruiter, credits):
    credits.cycle_starts_on = date(2026, 1, 1)
    credits.save()

    assert credits.cycle_ends_on == date(2026, 1, 31)
    assert credits.is_cycle_expired() is True


def test_a_current_cycle_has_not_expired(recruiter, credits):
    credits.cycle_starts_on = date.today()
    credits.save()

    assert credits.is_cycle_expired() is False


@pytest.mark.regression
def test_an_expired_cycle_resets_on_the_next_reveal(recruiter, credits, plans):
    """
    The nightly Beat task does the resetting, but a recruiter who logs in
    before it runs must not be told they are out of credits.
    """
    credits.reveals_used_this_month = 5
    credits.cycle_starts_on = date.today() - timedelta(days=40)
    credits.save()
    seeker = make_seeker('reset@test.com')

    result = CandidateProfileService.reveal_contact(recruiter, seeker)

    credits.refresh_from_db()
    assert result['already_revealed'] is False
    assert credits.reveals_used_this_month == 1
    assert credits.cycle_starts_on == date.today()


# --------------------------------------------------------------------------
# Profile detail
# --------------------------------------------------------------------------

def test_opening_a_profile_keeps_the_contact_masked(recruiter, credits, plans):
    seeker = make_seeker('masked@test.com')

    result = CandidateProfileService.get_profile(recruiter, seeker)

    assert result['contact_revealed'] is False


def test_opening_a_profile_after_paying_keeps_it_unmasked(recruiter, credits,
                                                          plans):
    seeker = make_seeker('unmasked@test.com')
    CandidateProfileService.reveal_contact(recruiter, seeker)

    result = CandidateProfileService.get_profile(recruiter, seeker)

    assert result['contact_revealed'] is True


def test_opening_a_profile_is_logged(recruiter, credits, plans):
    seeker = make_seeker('opened@test.com')

    CandidateProfileService.get_profile(recruiter, seeker)

    assert CandidateView.objects.filter(
        recruiter=recruiter, seeker=seeker,
        view_kind=CandidateView.ViewKind.DETAIL,
    ).exists()
    