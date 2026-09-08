"""
Application quota and lifecycle tests.

Both regression tests here cover the same root cause from opposite sides:
`Application.objects` is a SoftDeleteManager, so withdrawn applications
disappear from it. Reading quota through that manager handed the slot back;
reading the duplicate check through it let a doomed INSERT proceed.
"""
import pytest
from rest_framework.exceptions import ValidationError

from apps.applications.models import Application
from apps.applications.services import (
    ApplicationCreationService,
    ApplicationStatusService,
)
from apps.payments.services import FeatureGateService

pytestmark = pytest.mark.django_db


def _withdraw_all(seeker):
    for app in Application.objects.filter(seeker=seeker):
        ApplicationStatusService.update_status(
            app, Application.Status.WITHDRAWN, actor=seeker.user,
        )


# --------------------------------------------------------------------------
# Quota
# --------------------------------------------------------------------------

def test_free_seeker_can_apply_up_to_the_limit(free_seeker, six_jobs):
    for job in six_jobs[:5]:
        ApplicationCreationService.create(free_seeker, job)

    usage = FeatureGateService.can_apply_to_job(free_seeker.user)
    assert usage['used'] == 5
    assert usage['remaining'] == 0
    assert usage['can'] is False


def test_free_seeker_blocked_past_the_limit(free_seeker, six_jobs):
    for job in six_jobs[:5]:
        ApplicationCreationService.create(free_seeker, job)

    with pytest.raises(ValidationError):
        ApplicationCreationService.create(free_seeker, six_jobs[5])


def test_pro_seeker_has_no_application_limit(seeker, six_jobs):
    # `seeker` (unlike `free_seeker`) still has the signup trial running
    for job in six_jobs:
        ApplicationCreationService.create(seeker, job)

    usage = FeatureGateService.can_apply_to_job(seeker.user)
    assert usage['limit'] is None
    assert usage['can'] is True


@pytest.mark.regression
def test_withdrawing_does_not_refund_the_quota_slot(free_seeker, six_jobs):
    """
    Regression: withdrawal sets is_deleted=True, which hid the row from the
    default manager and reset the counter to zero. A free seeker could then
    apply, withdraw, and apply again forever.
    """
    for job in six_jobs[:5]:
        ApplicationCreationService.create(free_seeker, job)

    _withdraw_all(free_seeker)

    usage = FeatureGateService.can_apply_to_job(free_seeker.user)
    assert usage['used'] == 5, 'withdrawn applications must still count'
    assert usage['can'] is False

    with pytest.raises(ValidationError):
        ApplicationCreationService.create(free_seeker, six_jobs[5])


# --------------------------------------------------------------------------
# Duplicate / re-apply
# --------------------------------------------------------------------------

def test_cannot_apply_twice_to_the_same_job(seeker, job):
    ApplicationCreationService.create(seeker, job)

    with pytest.raises(ValidationError):
        ApplicationCreationService.create(seeker, job)


@pytest.mark.regression
def test_can_reapply_after_withdrawing(seeker, job):
    """
    Regression: the Python duplicate check used the soft-delete manager and
    passed, then the unconditional unique_together on (seeker, job) rejected
    the INSERT - surfacing as an IntegrityError / HTTP 500. A partial
    UniqueConstraint scoped to is_deleted=False now matches the Python check.
    """
    first = ApplicationCreationService.create(seeker, job)
    ApplicationStatusService.update_status(
        first, Application.Status.WITHDRAWN, actor=seeker.user,
    )

    second = ApplicationCreationService.create(seeker, job)

    assert second.pk != first.pk
    assert second.status == Application.Status.SUBMITTED
    # The withdrawn row survives, so the seeker keeps their history
    assert Application.all_objects.filter(seeker=seeker, job=job).count() == 2


def test_withdrawn_application_stays_visible_in_history(seeker, job):
    app = ApplicationCreationService.create(seeker, job)
    ApplicationStatusService.update_status(
        app, Application.Status.WITHDRAWN, actor=seeker.user,
    )

    assert not Application.objects.filter(pk=app.pk).exists()
    assert Application.all_objects.filter(pk=app.pk).exists()
