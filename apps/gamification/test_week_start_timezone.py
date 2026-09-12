"""
Which week a goal belongs to, around midnight IST.

Regression: `week_start` took the UTC date, while progress is counted with
`__date` lookups that bucket by the project time zone. Between midnight and
05:30 IST the two disagree, and on a Monday that put the user in last week -
their progress appeared to reset for five and a half hours.
"""

import datetime as dt

import pytest
from django.utils import timezone

from apps.gamification.services import week_start

# 00:30 IST on Monday 14 Sep 2026. In UTC this is still Sunday the 13th.
MONDAY_EARLY_IST = dt.datetime(2026, 9, 13, 19, 0, tzinfo=dt.timezone.utc)


@pytest.mark.regression
def test_just_after_midnight_ist_on_monday_the_week_has_already_turned():
    assert timezone.localdate(MONDAY_EARLY_IST) == dt.date(2026, 9, 14)
    assert MONDAY_EARLY_IST.date() == dt.date(2026, 9, 13), "precondition: UTC is still Sunday"

    assert week_start(MONDAY_EARLY_IST) == dt.date(2026, 9, 14)


@pytest.mark.parametrize(
    "moment, expected",
    [
        # Mid-week, where UTC and IST agree.
        (dt.datetime(2026, 9, 16, 9, 0, tzinfo=dt.timezone.utc), dt.date(2026, 9, 14)),
        # Sunday evening IST: still the week that began on the 14th.
        (dt.datetime(2026, 9, 20, 16, 0, tzinfo=dt.timezone.utc), dt.date(2026, 9, 14)),
        # 05:00 IST on Monday - UTC is Sunday, IST has turned over.
        (dt.datetime(2026, 9, 20, 23, 30, tzinfo=dt.timezone.utc), dt.date(2026, 9, 21)),
    ],
)
def test_the_week_runs_monday_to_sunday_in_local_time(moment, expected):
    assert week_start(moment) == expected


def test_it_works_with_no_argument():
    assert week_start().weekday() == 0
