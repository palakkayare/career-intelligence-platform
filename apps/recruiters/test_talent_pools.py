"""
Talent pools.

A pool stores criteria, not people. That is the whole difference from
SavedCandidate, and most of these tests exist to prove the distinction
holds: members are computed on read, so a pool cannot go stale and cannot
keep showing someone who has since gone private.
"""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationKind
from apps.recruiters.models import TalentPool
from apps.recruiters.services import TalentPoolService
from apps.seekers.models import SeekerProfile

pytestmark = pytest.mark.django_db


def make_seeker(email, **profile_fields):
    user = User.objects.create_user(
        email=email,
        password="TestPass123!",
        role=User.Role.SEEKER,
        is_email_verified=True,
    )
    profile = user.seeker_profile
    profile.visibility = SeekerProfile.Visibility.RECRUITERS_ONLY
    profile.is_open_to_opportunities = True
    for field, value in profile_fields.items():
        setattr(profile, field, value)
    profile.save()
    return profile


@pytest.fixture
def pool(recruiter, plans):
    return TalentPool.objects.create(
        recruiter=recruiter,
        name="Bangalore Backend",
        filters={"location_city": "Bangalore"},
    )


# --------------------------------------------------------------------------
# Membership is computed, not stored
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_a_pool_finds_matching_seekers(pool):
    """
    Regression: Feature 15 asks for "saved searches that auto-update as new
    candidates join". Nothing of the kind existed.
    """
    make_seeker("blr@test.com", location="Bangalore")
    make_seeker("pune@test.com", location="Pune")

    assert TalentPoolService.members(pool)["total"] == 1


@pytest.mark.regression
def test_a_pool_gains_members_without_being_touched(pool):
    """
    The auto-update. Nobody edits the pool; the criteria simply match more
    people than they did yesterday.
    """
    make_seeker("first@test.com", location="Bangalore")
    assert TalentPoolService.members(pool)["total"] == 1

    make_seeker("second@test.com", location="Bangalore")

    assert TalentPoolService.members(pool)["total"] == 2


@pytest.mark.regression
def test_a_seeker_who_goes_private_leaves_the_pool(pool):
    """
    A cached list would keep showing them. Computing on read is what makes
    the privacy setting mean something here.
    """
    seeker = make_seeker("leaving@test.com", location="Bangalore")
    assert TalentPoolService.members(pool)["total"] == 1

    seeker.visibility = SeekerProfile.Visibility.PRIVATE
    seeker.save()

    assert TalentPoolService.members(pool)["total"] == 0


def test_a_pool_with_no_filters_holds_everyone_discoverable(recruiter, plans):
    catch_all = TalentPool.objects.create(
        recruiter=recruiter,
        name="Everyone",
        filters={},
    )
    make_seeker("anyone@test.com")

    assert TalentPoolService.members(catch_all)["total"] == 1


def test_pool_results_are_paginated(pool):
    for index in range(5):
        make_seeker(f"page{index}@test.com", location="Bangalore")

    page = TalentPoolService.members(pool, page=1, page_size=2)

    assert page["total"] == 5
    assert len(page["seekers"]) == 2
    assert page["has_next"] is True


# --------------------------------------------------------------------------
# New arrivals
# --------------------------------------------------------------------------


def test_everything_is_new_before_the_first_check(pool):
    make_seeker("new@test.com", location="Bangalore")

    assert TalentPoolService.new_since_last_check(pool).count() == 1


def test_nothing_is_new_straight_after_a_check(pool):
    make_seeker("seen@test.com", location="Bangalore")
    TalentPoolService.mark_checked(pool)

    assert TalentPoolService.new_since_last_check(pool).count() == 0


def test_someone_joining_after_the_check_is_new(pool):
    make_seeker("early@test.com", location="Bangalore")
    TalentPoolService.mark_checked(pool)

    make_seeker("late@test.com", location="Bangalore")

    assert TalentPoolService.new_since_last_check(pool).count() == 1


@pytest.mark.regression
def test_editing_an_old_profile_does_not_make_it_new(pool):
    """
    "New" has to mean newly joined. Keying off updated_at would resend the
    same person every time they touched their bio.
    """
    seeker = make_seeker("existing@test.com", location="Bangalore")
    TalentPoolService.mark_checked(pool)

    seeker.bio = "Updated my bio today"
    seeker.save()

    assert TalentPoolService.new_since_last_check(pool).count() == 0


def test_someone_outside_the_filters_is_not_new(pool):
    make_seeker("elsewhere@test.com", location="Pune")

    assert TalentPoolService.new_since_last_check(pool).count() == 0


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------


def test_new_arrivals_notify_the_recruiter(pool, recruiter):
    make_seeker("arrival@test.com", location="Bangalore")

    count = TalentPoolService.notify_new_members(pool)

    assert count == 1
    assert Notification.objects.filter(
        user=recruiter.user,
        kind=NotificationKind.NEW_MATCHING_CANDIDATE,
    ).exists()


def test_the_notification_names_the_pool(pool, recruiter):
    make_seeker("arrival@test.com", location="Bangalore")

    TalentPoolService.notify_new_members(pool)

    notif = Notification.objects.get(user=recruiter.user)
    assert "Bangalore Backend" in notif.title


def test_no_arrivals_means_no_notification(pool, recruiter):
    assert TalentPoolService.notify_new_members(pool) == 0
    assert not Notification.objects.filter(user=recruiter.user).exists()


@pytest.mark.regression
def test_the_same_arrival_is_not_reported_twice(pool, recruiter):
    """
    The marker has to move, or every sweep would re-report the same people
    until the recruiter stopped reading the emails.
    """
    make_seeker("once@test.com", location="Bangalore")

    TalentPoolService.notify_new_members(pool)
    second_sweep = TalentPoolService.notify_new_members(pool)

    assert second_sweep == 0
    assert Notification.objects.filter(user=recruiter.user).count() == 1


@pytest.mark.regression
def test_an_idle_pool_still_moves_its_marker(pool):
    """
    Otherwise a pool that found nothing would rescan the same widening
    window forever.
    """
    assert pool.last_checked_at is None

    TalentPoolService.notify_new_members(pool)

    pool.refresh_from_db()
    assert pool.last_checked_at is not None


def test_a_muted_pool_sends_nothing(pool, recruiter):
    pool.notify_on_new = False
    pool.save()
    make_seeker("unwanted@test.com", location="Bangalore")

    assert TalentPoolService.notify_new_members(pool) == 0
    assert not Notification.objects.filter(user=recruiter.user).exists()


def test_the_notification_is_batched_not_instant(pool, recruiter):
    from apps.notifications.models import DeliveryPriority

    make_seeker("arrival@test.com", location="Bangalore")
    TalentPoolService.notify_new_members(pool)

    notif = Notification.objects.get(user=recruiter.user)
    assert notif.delivery_priority == DeliveryPriority.DIGEST


# --------------------------------------------------------------------------
# The sweep task
# --------------------------------------------------------------------------


def test_the_sweep_covers_every_pool(recruiter, plans):
    from apps.recruiters.tasks import sweep_talent_pools

    TalentPool.objects.create(
        recruiter=recruiter,
        name="Bangalore",
        filters={"location_city": "Bangalore"},
    )
    TalentPool.objects.create(
        recruiter=recruiter,
        name="Pune",
        filters={"location_city": "Pune"},
    )
    make_seeker("blr@test.com", location="Bangalore")
    make_seeker("pune@test.com", location="Pune")

    result = sweep_talent_pools()

    assert result["pools_with_new_candidates"] == 2


def test_the_sweep_skips_muted_pools(recruiter, plans):
    from apps.recruiters.tasks import sweep_talent_pools

    TalentPool.objects.create(
        recruiter=recruiter,
        name="Muted",
        filters={},
        notify_on_new=False,
    )
    make_seeker("anyone@test.com")

    assert sweep_talent_pools()["pools_with_new_candidates"] == 0


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@pytest.fixture
def business_recruiter(recruiter, plans):
    """
    Talent pools sit behind the same gate as candidate search, which is a
    Business-plan feature. The signup trial is Pro - a seeker plan - so a
    plain recruiter fixture gets a 403.
    """
    from datetime import timedelta
    from decimal import Decimal

    from apps.payments.models import Plan, Subscription

    business = Plan.objects.create(
        name="Business Monthly",
        slug="business_monthly",
        tier=Plan.Tier.BUSINESS,
        billing_period=Plan.BillingPeriod.MONTHLY,
        price_inr=Decimal("2999"),
        has_candidate_search=True,
        max_team_members=5,
        sort_order=3,
    )

    now = timezone.now()
    sub = recruiter.user.subscriptions.order_by("-created_at").first()

    # The signup trial is only granted when plans already exist, and fixture
    # ordering does not guarantee that - so create the subscription if the
    # signal did not.
    if sub is None:
        Subscription.objects.create(
            user=recruiter.user,
            plan=business,
            status=Subscription.Status.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        return recruiter

    sub.plan = business
    sub.status = Subscription.Status.ACTIVE
    sub.trial_ends_at = None
    sub.current_period_end = now + timedelta(days=30)
    sub.save()
    return recruiter


@pytest.fixture
def recruiter_client(business_recruiter):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=business_recruiter.user)
    return client


def test_a_recruiter_can_create_a_pool(recruiter_client):
    response = recruiter_client.post(
        "/api/v1/candidates/pools/",
        {
            "name": "Senior Python",
            "filters": {"location_city": "Bangalore"},
        },
        format="json",
    )

    assert response.status_code == 201
    assert TalentPool.objects.filter(name="Senior Python").exists()


def test_pool_names_are_unique_per_recruiter(recruiter_client, pool):
    response = recruiter_client.post(
        "/api/v1/candidates/pools/",
        {
            "name": pool.name,
            "filters": {},
        },
        format="json",
    )

    assert response.status_code == 400


def test_a_recruiter_only_sees_their_own_pools(recruiter_client, pool, plans):
    other_user = User.objects.create_user(
        email="other-recruiter@test.com",
        password="TestPass123!",
        role=User.Role.RECRUITER,
        is_email_verified=True,
    )
    TalentPool.objects.create(
        recruiter=other_user.recruiter_profile,
        name="Theirs",
        filters={},
    )

    response = recruiter_client.get("/api/v1/candidates/pools/")

    names = {row["name"] for row in response.data["results"]}
    assert names == {pool.name}


def test_the_member_count_is_live(recruiter_client, pool):
    make_seeker("counted@test.com", location="Bangalore")

    response = recruiter_client.get(f"/api/v1/candidates/pools/{pool.pk}/")

    assert response.data["member_count"] == 1


def test_the_members_endpoint_lists_candidates(recruiter_client, pool):
    make_seeker("listed@test.com", location="Bangalore")

    response = recruiter_client.get(
        f"/api/v1/candidates/pools/{pool.pk}/members/",
    )

    assert response.status_code == 200
    assert response.data["total"] == 1
    assert len(response.data["candidates"]) == 1


def test_a_pool_can_be_deleted(recruiter_client, pool):
    response = recruiter_client.delete(f"/api/v1/candidates/pools/{pool.pk}/")

    assert response.status_code == 204
    assert not TalentPool.objects.filter(pk=pool.pk).exists()


def test_seekers_cannot_use_talent_pools(seeker_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=seeker_user)

    assert client.get("/api/v1/candidates/pools/").status_code == 403
