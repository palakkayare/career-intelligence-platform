"""
Audit trail tests.
"""
import pytest

from apps.audit.context import clear_context, set_context
from apps.audit.models import AuditLog
from apps.jobs.models import Job

pytestmark = pytest.mark.django_db


def _entries(instance, action=None):
    qs = AuditLog.objects.filter(
        model_name=f'{instance._meta.app_label}.{instance._meta.object_name}',
        object_id=str(instance.pk),
    )
    return qs.filter(action=action) if action else qs


@pytest.fixture
def acting_user(seeker_user):
    """Simulate the middleware having populated the request context."""
    set_context(user=seeker_user, ip_address='203.0.113.7', user_agent='pytest')
    yield seeker_user
    clear_context()


# --------------------------------------------------------------------------
# Basic capture
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_create_is_logged(make_job):
    """
    Regression: the blueprint lists AuditLog as a Phase 2 deliverable and a
    core data model, but no model, signal or library existed.
    """
    job = make_job()

    entry = _entries(job, AuditLog.Action.CREATE).get()
    assert entry.new_value['title'] == job.title
    assert entry.object_repr


def test_update_records_only_changed_fields(make_job):
    job = make_job()
    job.title = 'Senior Backend Developer'
    job.save()

    entry = _entries(job, AuditLog.Action.UPDATE).latest('created_at')
    assert entry.old_value == {'title': 'Backend Developer'}
    assert entry.new_value == {'title': 'Senior Backend Developer'}
    assert entry.changed_fields == ['title']


def test_save_without_changes_is_not_logged(make_job):
    job = make_job()
    before = _entries(job, AuditLog.Action.UPDATE).count()

    job.save()

    assert _entries(job, AuditLog.Action.UPDATE).count() == before


def test_soft_delete_is_recorded_as_an_update(make_job):
    job = make_job()
    job.soft_delete()

    entry = _entries(job, AuditLog.Action.UPDATE).latest('created_at')
    assert entry.old_value['is_deleted'] is False
    assert entry.new_value['is_deleted'] is True


def test_hard_delete_is_logged(make_job):
    job = make_job()
    pk = job.pk
    job.delete()

    assert AuditLog.objects.filter(
        model_name='jobs.Job', object_id=str(pk),
        action=AuditLog.Action.DELETE,
    ).exists()


def test_unregistered_model_is_not_logged(skill):
    """Only models in AUDITED_MODELS are watched."""
    from apps.industries.models import Industry

    industry = Industry.objects.create(name='Healthcare')

    assert not _entries(industry).exists()


# --------------------------------------------------------------------------
# Request context
# --------------------------------------------------------------------------

def test_actor_and_ip_are_captured(acting_user, make_job):
    job = make_job()

    entry = _entries(job, AuditLog.Action.CREATE).get()
    assert entry.user_id == acting_user.id
    assert entry.user_email == acting_user.email
    assert entry.ip_address == '203.0.113.7'


def test_actions_outside_a_request_are_attributed_to_the_system(make_job):
    clear_context()
    job = make_job()

    entry = _entries(job, AuditLog.Action.CREATE).get()
    assert entry.user is None
    assert entry.user_email == ''


def test_email_survives_the_actor_being_removed(acting_user, make_job):
    """
    user is SET_NULL, but user_email is copied at write time so the trail
    still names who acted. Users are never hard-deleted here (Subscription.user
    is PROTECT), so the realistic path is soft delete followed by an eventual
    purge - the FK is simulated directly.
    """
    job = make_job()
    entry = _entries(job, AuditLog.Action.CREATE).get()
    email = acting_user.email

    acting_user.soft_delete()
    entry.refresh_from_db()

    # Soft delete leaves the link intact; the copied email is what guarantees
    # the actor stays identifiable once the row is eventually purged.
    assert entry.user_email == email

    AuditLog.objects.filter(pk=entry.pk).update(user=None)
    entry.refresh_from_db()

    assert entry.user is None
    assert entry.user_email == email
# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------

def test_sensitive_fields_are_never_stored(plans):
    from apps.accounts.models import User

    user = User.objects.create_user(
        email='audited@test.com', password='TestPass123!',
    )

    entry = _entries(user, AuditLog.Action.CREATE).get()
    assert 'password' not in entry.new_value
    assert 'google_sub' not in entry.new_value
    assert entry.new_value['email'] == 'audited@test.com'


def test_audit_failure_does_not_break_the_operation(make_job, monkeypatch):
    """An audit problem must never take down the request it is observing."""
    def boom(*args, **kwargs):
        raise RuntimeError('audit backend down')

    monkeypatch.setattr(AuditLog.objects, 'create', boom)

    job = make_job()          # must not raise
    assert job.pk is not None
