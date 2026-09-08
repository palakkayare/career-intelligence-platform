"""
Notification delivery tests, focused on the mobile push path.
"""
import pytest

from apps.notifications.models import (
    DeliveryPriority, Notification, NotificationKind, NotificationPreferences,
)
from apps.notifications.service import NotificationService

pytestmark = pytest.mark.django_db


def _notify(user, kind=NotificationKind.PAYMENT_SUCCESS):
    return NotificationService.create(
        user=user, kind=kind, title='Payment received',
        message='Your Pro subscription is active.',
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
    seeker_user.fcm_token = 'fcm-token-abc123'
    seeker_user.save(update_fields=['fcm_token'])

    prefs = seeker_user.notification_preferences
    prefs.push_enabled = True
    prefs.save(update_fields=['push_enabled'])
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
    prefs.save(update_fields=['push_enabled'])

    notif = _notify(seeker_user)

    assert NotificationService.push_notification(notif) is False


def test_no_push_when_the_user_opted_out(push_ready):
    prefs = push_ready.notification_preferences
    prefs.push_enabled = False
    prefs.save(update_fields=['push_enabled'])

    notif = _notify(push_ready)

    assert NotificationService.push_notification(notif) is False


def test_push_is_off_by_default(seeker_user):
    """A device token alone is not consent."""
    seeker_user.fcm_token = 'fcm-token-abc123'
    seeker_user.save(update_fields=['fcm_token'])

    assert seeker_user.notification_preferences.push_enabled is False


# --------------------------------------------------------------------------
# Device registration
# --------------------------------------------------------------------------

def test_registering_a_device_stores_the_token(seeker_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=seeker_user)

    response = client.post('/api/v1/notifications/device-token/', {
        'fcm_token': 'fcm-token-xyz',
    }, format='json')

    seeker_user.refresh_from_db()
    assert response.status_code == 200
    assert seeker_user.fcm_token == 'fcm-token-xyz'
    assert seeker_user.notification_preferences.push_enabled is True


def test_registering_can_leave_push_off(seeker_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=seeker_user)

    client.post('/api/v1/notifications/device-token/', {
        'fcm_token': 'fcm-token-xyz', 'enable_push': False,
    }, format='json')

    seeker_user.refresh_from_db()
    assert seeker_user.fcm_token == 'fcm-token-xyz'
    assert seeker_user.notification_preferences.push_enabled is False


def test_clearing_the_device_stops_push(push_ready):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=push_ready)

    response = client.delete('/api/v1/notifications/device-token/')

    push_ready.refresh_from_db()
    assert response.status_code == 204
    assert push_ready.fcm_token is None
    assert push_ready.notification_preferences.push_enabled is False


def test_device_token_requires_authentication():
    from rest_framework.test import APIClient

    response = APIClient().post('/api/v1/notifications/device-token/', {
        'fcm_token': 'fcm-token-xyz',
    }, format='json')

    assert response.status_code in (401, 403)