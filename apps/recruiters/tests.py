"""
Candidate discovery tests, focused on who is allowed to be found.
"""

from datetime import date, timedelta

import pytest

from apps.seekers.models import SeekerProfile

pytestmark = pytest.mark.django_db


def _is_discoverable(profile):
    return SeekerProfile.discoverable().filter(pk=profile.pk).exists()


def test_recruiters_only_profile_is_discoverable(seeker):
    seeker.visibility = SeekerProfile.Visibility.RECRUITERS_ONLY
    seeker.save()
    assert _is_discoverable(seeker)


def test_public_profile_is_discoverable(seeker):
    seeker.visibility = SeekerProfile.Visibility.PUBLIC
    seeker.save()
    assert _is_discoverable(seeker)


@pytest.mark.regression
def test_private_profile_is_not_discoverable(seeker):
    """
    Regression: candidate search filtered on `is_open_to_opportunities` only
    and never read `visibility`, so a seeker who chose PRIVATE still appeared
    in recruiter search and could be opened directly by public_id.
    """
    seeker.visibility = SeekerProfile.Visibility.PRIVATE
    seeker.save()

    assert seeker.is_open_to_opportunities is True, "the opt-in toggle stays on"
    assert not _is_discoverable(seeker), "PRIVATE must override the toggle"


def test_opted_out_profile_is_not_discoverable(seeker):
    seeker.visibility = SeekerProfile.Visibility.PUBLIC
    seeker.is_open_to_opportunities = False
    seeker.save()
    assert not _is_discoverable(seeker)


def test_unverified_email_is_not_discoverable(seeker):
    seeker.user.is_email_verified = False
    seeker.user.save()
    assert not _is_discoverable(seeker)


def test_expired_searchable_date_is_not_discoverable(seeker):
    seeker.searchable_until_date = date.today() - timedelta(days=1)
    seeker.save()
    assert not _is_discoverable(seeker)


def test_search_and_detail_share_one_definition():
    """
    The rule lives on the model. If either consumer stops calling
    discoverable(), the two paths can drift apart again.
    """
    import inspect

    from apps.recruiters.candidate_services import CandidateSearchService
    from apps.recruiters.candidate_views import _searchable_seeker_or_404

    assert "discoverable()" in inspect.getsource(CandidateSearchService._base_queryset)
    assert "discoverable()" in inspect.getsource(_searchable_seeker_or_404)
