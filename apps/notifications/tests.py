"""
Notification delivery tests, focused on the mobile push path.
"""

import pytest

from apps.notifications.models import (
    DeliveryPriority,
    Notification,
    NotificationKind,
)
from apps.notifications.service import NotificationService

pytestmark = pytest.mark.django_db


def _notify(user, kind=NotificationKind.PAYMENT_SUCCESS):
    return NotificationService.create(
        user=user,
        kind=kind,
        title="Payment received",
        message="Your Pro subscription is active.",
    )


@pytest.fixture
def push_ready(seeker_user):
    """
    A user with a device registered and push switched on.

    Mutates the preferences through the reverse accessor rather than
    re-fetching them. The signal that creates NotificationPreferences also
    populates Django's reverse cache on the user, so a separately fetched
    copy would be saved while the cached one stayed stale.
    """
    seeker_user.fcm_token = "fcm-token-abc123"
    seeker_user.save(update_fields=["fcm_token"])

    prefs = seeker_user.notification_preferences
    prefs.push_enabled = True
    prefs.save(update_fields=["push_enabled"])
    return seeker_user


# --------------------------------------------------------------------------
# In-app delivery
# --------------------------------------------------------------------------


def test_notification_is_always_stored(seeker_user):
    notif = _notify(seeker_user)

    assert Notification.objects.filter(pk=notif.pk).exists()
    assert notif.is_read is False


def test_profile_views_are_in_app_only(seeker_user):
    notif = _notify(seeker_user, kind=NotificationKind.PROFILE_VIEWED)

    assert notif.delivery_priority == DeliveryPriority.NONE


# --------------------------------------------------------------------------
# Push
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_push_is_attempted_when_the_user_is_set_up(push_ready):
    """
    Regression: the blueprint asks for a push_notification() stub on
    NotificationService for the future mobile app. It did not exist, and
    neither did any way to set fcm_token.
    """
    notif = _notify(push_ready)

    assert NotificationService.push_notification(notif) is True


def test_no_push_without_a_device_token(seeker_user):
    prefs = seeker_user.notification_preferences
    prefs.push_enabled = True
    prefs.save(update_fields=["push_enabled"])

    notif = _notify(seeker_user)

    assert NotificationService.push_notification(notif) is False


def test_no_push_when_the_user_opted_out(push_ready):
    prefs = push_ready.notification_preferences
    prefs.push_enabled = False
    prefs.save(update_fields=["push_enabled"])

    notif = _notify(push_ready)

    assert NotificationService.push_notification(notif) is False


def test_push_is_off_by_default(seeker_user):
    """A device token alone is not consent."""
    seeker_user.fcm_token = "fcm-token-abc123"
    seeker_user.save(update_fields=["fcm_token"])

    assert seeker_user.notification_preferences.push_enabled is False


# --------------------------------------------------------------------------
# Device registration
# --------------------------------------------------------------------------


def test_registering_a_device_stores_the_token(seeker_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=seeker_user)

    response = client.post(
        "/api/v1/notifications/device-token/",
        {
            "fcm_token": "fcm-token-xyz",
        },
        format="json",
    )

    seeker_user.refresh_from_db()
    assert response.status_code == 200
    assert seeker_user.fcm_token == "fcm-token-xyz"
    assert seeker_user.notification_preferences.push_enabled is True


def test_registering_can_leave_push_off(seeker_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=seeker_user)

    client.post(
        "/api/v1/notifications/device-token/",
        {
            "fcm_token": "fcm-token-xyz",
            "enable_push": False,
        },
        format="json",
    )

    seeker_user.refresh_from_db()
    assert seeker_user.fcm_token == "fcm-token-xyz"
    assert seeker_user.notification_preferences.push_enabled is False


def test_clearing_the_device_stops_push(push_ready):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=push_ready)

    response = client.delete("/api/v1/notifications/device-token/")

    push_ready.refresh_from_db()
    assert response.status_code == 204
    assert push_ready.fcm_token is None
    assert push_ready.notification_preferences.push_enabled is False


def test_device_token_requires_authentication():
    from rest_framework.test import APIClient

    response = APIClient().post(
        "/api/v1/notifications/device-token/",
        {
            "fcm_token": "fcm-token-xyz",
        },
        format="json",
    )

    assert response.status_code in (401, 403)


# --------------------------------------------------------------------------
# Triggers that were declared but never fired
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_a_withdrawal_notifies_the_recruiter(seeker, job, recruiter_user):
    """
    Regression: APPLICATION_WITHDRAWN existed as a kind with no trigger. A
    candidate the recruiter was interviewing would simply vanish from the
    list with no explanation.
    """
    from apps.applications.models import Application
    from apps.applications.services import ApplicationCreationService, ApplicationStatusService

    application = ApplicationCreationService.create(seeker, job)
    Notification.objects.filter(user=recruiter_user).delete()

    ApplicationStatusService.update_status(
        application,
        Application.Status.WITHDRAWN,
        actor=seeker.user,
    )

    notif = Notification.objects.get(
        user=recruiter_user,
        kind=NotificationKind.APPLICATION_WITHDRAWN,
    )
    assert job.title in notif.message


def test_the_seeker_is_not_told_about_their_own_withdrawal(seeker, job):
    """They just did it. The status-change notice already covers it."""
    from apps.applications.models import Application
    from apps.applications.services import ApplicationCreationService, ApplicationStatusService

    application = ApplicationCreationService.create(seeker, job)
    ApplicationStatusService.update_status(
        application,
        Application.Status.WITHDRAWN,
        actor=seeker.user,
    )

    assert not Notification.objects.filter(
        user=seeker.user,
        kind=NotificationKind.APPLICATION_WITHDRAWN,
    ).exists()


@pytest.mark.regression
def test_expiring_a_subscription_notifies_the_user(seeker_user):
    """
    Regression: SUBSCRIPTION_EXPIRED had no trigger, so paid features simply
    stopped working with no explanation.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.payments.services import SubscriptionService

    sub = seeker_user.subscriptions.get()
    sub.trial_ends_at = timezone.now() - timedelta(days=1)
    sub.save()

    SubscriptionService.expire_ended_subscriptions()

    assert Notification.objects.filter(
        user=seeker_user,
        kind=NotificationKind.SUBSCRIPTION_EXPIRED,
    ).exists()


def test_the_expiry_sweep_still_reports_a_count(seeker_user):
    from datetime import timedelta

    from django.utils import timezone

    from apps.payments.services import SubscriptionService

    sub = seeker_user.subscriptions.get()
    sub.trial_ends_at = timezone.now() - timedelta(days=1)
    sub.save()

    assert SubscriptionService.expire_ended_subscriptions() == 1


def test_the_sweep_is_a_no_op_when_nothing_has_expired(seeker_user):
    from apps.payments.services import SubscriptionService

    assert SubscriptionService.expire_ended_subscriptions() == 0
    assert not Notification.objects.filter(
        kind=NotificationKind.SUBSCRIPTION_EXPIRED,
    ).exists()


@pytest.mark.regression
def test_a_finished_resume_analysis_notifies_the_owner(seeker_user):
    """
    Regression: the blueprint lists "resume analysis complete" as a trigger
    and there was no kind for it, let alone a notification.
    """
    from apps.notifications.triggers import notify_resume_analysis_complete
    from apps.resumes.models import Resume

    resume = Resume.objects.create(
        user=seeker_user,
        name="My CV",
        original_filename="cv.pdf",
        file="resumes/cv.pdf",
        file_size_bytes=1000,
        status=Resume.Status.PARSED,
        ats_score=78,
    )

    notify_resume_analysis_complete(resume)

    notif = Notification.objects.get(
        user=seeker_user,
        kind=NotificationKind.RESUME_ANALYSIS_COMPLETE,
    )
    assert "78" in notif.message
    assert notif.context["ats_score"] == 78


def test_job_alerts_arrive_as_one_digest_not_one_per_job(seeker_user):
    """
    Ten separate emails about ten jobs is how a useful feature becomes an
    unsubscribe.
    """
    from apps.notifications.triggers import notify_new_matching_jobs

    matches = [
        {
            "job_id": str(i),
            "job_title": f"Job {i}",
            "company_name": "Test Corp",
            "score": 90 - i,
        }
        for i in range(10)
    ]

    notify_new_matching_jobs(seeker_user, matches)

    notifs = Notification.objects.filter(
        user=seeker_user,
        kind=NotificationKind.NEW_MATCHING_JOB,
    )
    assert notifs.count() == 1
    assert "10 new jobs" in notifs.first().title


def test_the_best_match_leads_the_digest(seeker_user):
    from apps.notifications.triggers import notify_new_matching_jobs

    notify_new_matching_jobs(
        seeker_user,
        [
            {
                "job_id": "1",
                "job_title": "Best Fit",
                "company_name": "Test Corp",
                "score": 95,
            },
            {
                "job_id": "2",
                "job_title": "Worse Fit",
                "company_name": "Test Corp",
                "score": 71,
            },
        ],
    )

    notif = Notification.objects.get(
        user=seeker_user,
        kind=NotificationKind.NEW_MATCHING_JOB,
    )
    assert "Best Fit" in notif.message


def test_an_empty_match_list_sends_nothing(seeker_user):
    """No matches this week is not news."""
    from apps.notifications.triggers import notify_new_matching_jobs

    assert notify_new_matching_jobs(seeker_user, []) is None
    assert not Notification.objects.filter(
        user=seeker_user,
        kind=NotificationKind.NEW_MATCHING_JOB,
    ).exists()


@pytest.mark.regression
def test_job_alerts_are_batched_not_emailed_immediately(seeker_user):
    """
    Weekly alerts belong in the digest. Sending them instantly would mean an
    email every time the six-hourly scoring task finds something.
    """
    from apps.notifications.triggers import notify_new_matching_jobs

    notif = notify_new_matching_jobs(
        seeker_user,
        [
            {
                "job_id": "1",
                "job_title": "A Job",
                "company_name": "Test Corp",
                "score": 80,
            },
        ],
    )

    assert notif.delivery_priority == DeliveryPriority.DIGEST
