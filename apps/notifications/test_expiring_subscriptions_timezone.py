"""
Which subscriptions the expiry warning picks up.

Regression: the target day came from the UTC date while the lookup buckets by
the project time zone. Correct at the 09:30 IST schedule, wrong for any run
before 05:30 IST - including a retry or a changed schedule.
"""

import datetime as dt
from unittest import mock

import pytest
from django.utils import timezone

from apps.notifications.tasks import check_expiring_subscriptions
from apps.payments.models import Subscription

pytestmark = pytest.mark.django_db

# 01:00 IST on 12 Sep 2026; UTC is still 11 Sep.
EARLY_IST = dt.datetime(2026, 9, 11, 19, 30, tzinfo=dt.timezone.utc)


def make_subscription(seeker_user, plans, ends_on):
    """A subscription ending at noon IST on the given local date."""
    ends_at = timezone.make_aware(dt.datetime.combine(ends_on, dt.time(12, 0)))
    return Subscription.objects.create(
        user=seeker_user,
        plan=plans["pro"],
        status=Subscription.Status.ACTIVE,
        auto_renew=False,
        current_period_start=ends_at - dt.timedelta(days=30),
        current_period_end=ends_at,
    )


@pytest.mark.regression
def test_a_run_before_0530_ist_still_picks_the_right_day(seeker_user, plans):
    """Three days from 12 Sep IST is 15 Sep - not 14, which UTC would give."""
    seeker_user.subscriptions.all().delete()
    make_subscription(seeker_user, plans, dt.date(2026, 9, 15))

    with mock.patch("django.utils.timezone.now", return_value=EARLY_IST):
        notified = check_expiring_subscriptions()

    assert notified == 1


def test_a_subscription_ending_on_another_day_is_left_alone(seeker_user, plans):
    seeker_user.subscriptions.all().delete()
    make_subscription(seeker_user, plans, dt.date(2026, 9, 14))

    with mock.patch("django.utils.timezone.now", return_value=EARLY_IST):
        notified = check_expiring_subscriptions()

    assert notified == 0


def test_an_auto_renewing_subscription_is_not_warned(seeker_user, plans):
    seeker_user.subscriptions.all().delete()
    subscription = make_subscription(seeker_user, plans, dt.date(2026, 9, 15))
    subscription.auto_renew = True
    subscription.save(update_fields=["auto_renew"])

    with mock.patch("django.utils.timezone.now", return_value=EARLY_IST):
        notified = check_expiring_subscriptions()

    assert notified == 0
