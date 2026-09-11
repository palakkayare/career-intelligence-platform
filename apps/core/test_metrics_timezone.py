"""
Daily activity series use the project time zone for both sides of the join.
"""

import datetime as dt
from unittest import mock

import pytest

from apps.core.metrics import ActivityMetrics

pytestmark = pytest.mark.django_db

# 00:30 IST on 12 Sep 2026 - still 11 Sep in UTC.
EARLY_MORNING_IST = dt.datetime(2026, 9, 11, 19, 0, tzinfo=dt.timezone.utc)


@pytest.mark.regression
def test_todays_activity_counts_between_midnight_and_0530_ist(seeker, job):
    """
    Regression: rows were bucketed by IST day but "today" was the UTC date, so
    for five and a half hours after midnight IST the chart ended on yesterday
    and today's applications were missing. Two date-based tests failed
    whenever the suite ran in that window.
    """
    from apps.applications.models import Application
    from apps.applications.services import ApplicationCreationService

    application = ApplicationCreationService.create(seeker, job)
    Application.all_objects.filter(pk=application.pk).update(submitted_at=EARLY_MORNING_IST)

    with mock.patch("django.utils.timezone.now", return_value=EARLY_MORNING_IST):
        series = ActivityMetrics.applications_per_day(days=7)

    assert series[-1]["date"] == "2026-09-12"
    assert series[-1]["count"] == 1
