"""
User manager and soft-delete tests.
"""
import pytest

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_create_user_defaults_to_seeker(plans):
    user = User.objects.create_user(email='a@test.com', password='TestPass123!')
    assert user.role == User.Role.SEEKER
    assert user.is_seeker is True
    assert user.check_password('TestPass123!')


def test_create_superuser_is_staff_and_verified(plans):
    admin = User.objects.create_superuser(
        email='admin@test.com', password='TestPass123!',
    )
    assert admin.is_staff
    assert admin.is_superuser
    assert admin.role == User.Role.ADMIN
    assert admin.is_email_verified


def test_oauth_user_has_no_usable_password(plans):
    user = User.objects.create_oauth_user(
        email='google@test.com', google_sub='sub-123', full_name='G User',
    )
    assert user.has_usable_password() is False
    assert user.is_email_verified is True
    assert user.auth_provider == User.AuthProvider.GOOGLE


@pytest.mark.regression
def test_soft_deleted_user_is_hidden_from_default_manager(seeker_user):
    """
    Regression: User overrides `objects` with UserManager, which shadowed the
    SoftDeleteManager inherited from SoftDeleteModel. Soft-deleted users stayed
    fully queryable - and therefore able to authenticate.
    """
    seeker_user.soft_delete()

    assert not User.objects.filter(pk=seeker_user.pk).exists()
    assert User.all_objects.filter(pk=seeker_user.pk).exists()


@pytest.mark.regression
def test_soft_deleted_user_cannot_authenticate(seeker_user):
    from django.contrib.auth import authenticate

    seeker_user.soft_delete()

    assert authenticate(email='seeker@test.com', password='TestPass123!') is None


def test_restore_brings_the_user_back(seeker_user):
    seeker_user.soft_delete()
    assert not User.objects.filter(pk=seeker_user.pk).exists()

    User.all_objects.get(pk=seeker_user.pk).restore()

    assert User.objects.filter(pk=seeker_user.pk).exists()


# --------------------------------------------------------------------------
# Data export
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_export_covers_the_main_sections(seeker):
    """
    Regression: Feature 01 asks for "account deactivation with data export
    (PDPB compliance)". Neither endpoint existed.
    """
    from apps.accounts.privacy import DataExportService

    data = DataExportService.build(seeker.user)

    assert data['account']['email'] == seeker.user.email
    assert data['export_metadata']['format_version']
    for section in ('account', 'security_activity', 'notifications',
                    'referrals', 'seeker'):
        assert section in data


def test_export_omits_authentication_secrets(seeker):
    import json

    from apps.accounts.privacy import DataExportService

    blob = json.dumps(DataExportService.build(seeker.user), default=str)

    assert seeker.user.password not in blob
    assert 'password' not in DataExportService.build(seeker.user)['account']


def test_export_includes_applications_including_withdrawn(seeker, job):
    from apps.accounts.privacy import DataExportService
    from apps.applications.models import Application
    from apps.applications.services import (
        ApplicationCreationService, ApplicationStatusService,
    )

    app = ApplicationCreationService.create(seeker, job)
    ApplicationStatusService.update_status(
        app, Application.Status.WITHDRAWN, actor=seeker.user,
    )

    exported = DataExportService.build(seeker.user)['seeker']['applications']

    assert len(exported) == 1
    assert exported[0]['withdrawn'] is True
    assert exported[0]['job_title'] == job.title


def test_recruiter_export_has_no_seeker_section(recruiter):
    from apps.accounts.privacy import DataExportService

    data = DataExportService.build(recruiter.user)

    assert 'recruiter' in data
    assert 'seeker' not in data


# --------------------------------------------------------------------------
# Account deactivation
# --------------------------------------------------------------------------

def test_deactivation_closes_the_account(seeker):
    from apps.accounts.privacy import AccountDeactivationService

    AccountDeactivationService.deactivate(
        seeker.user, password='TestPass123!', reason='Found a job',
    )

    seeker.user.refresh_from_db()
    assert seeker.user.is_deleted
    assert seeker.user.deactivation_reason == 'Found a job'
    assert not User.objects.filter(pk=seeker.user.pk).exists()


def test_deactivation_requires_the_password(seeker):
    from rest_framework.exceptions import ValidationError

    from apps.accounts.privacy import AccountDeactivationService

    with pytest.raises(ValidationError):
        AccountDeactivationService.deactivate(seeker.user, password='wrong')

    seeker.user.refresh_from_db()
    assert not seeker.user.is_deleted


def test_oauth_account_closes_without_a_password(plans):
    from apps.accounts.privacy import AccountDeactivationService

    user = User.objects.create_oauth_user(
        email='oauth@test.com', google_sub='sub-9', full_name='OAuth User',
    )

    AccountDeactivationService.deactivate(user)

    user.refresh_from_db()
    assert user.is_deleted


def test_deactivation_withdraws_live_applications(seeker, six_jobs):
    from apps.accounts.privacy import AccountDeactivationService
    from apps.applications.models import Application
    from apps.applications.services import ApplicationCreationService

    for job in six_jobs[:3]:
        ApplicationCreationService.create(seeker, job)

    summary = AccountDeactivationService.deactivate(
        seeker.user, password='TestPass123!',
    )

    assert summary['applications_withdrawn'] == 3
    assert not Application.objects.filter(seeker=seeker).exists()
    assert Application.all_objects.filter(seeker=seeker).count() == 3


def test_deactivation_stops_billing(seeker):
    from apps.accounts.privacy import AccountDeactivationService

    summary = AccountDeactivationService.deactivate(
        seeker.user, password='TestPass123!',
    )

    subscription = seeker.user.subscriptions.get()
    assert summary['subscription_cancelled'] is True
    assert subscription.auto_renew is False
    assert subscription.cancelled_at is not None


def test_deactivation_hides_the_profile(seeker):
    from apps.accounts.privacy import AccountDeactivationService
    from apps.seekers.models import SeekerProfile

    AccountDeactivationService.deactivate(seeker.user, password='TestPass123!')

    seeker.refresh_from_db()
    assert seeker.visibility == SeekerProfile.Visibility.PRIVATE
    assert seeker.is_open_to_opportunities is False
    assert not SeekerProfile.discoverable().filter(pk=seeker.pk).exists()


def test_deactivated_user_cannot_log_in(seeker):
    from django.contrib.auth import authenticate

    from apps.accounts.privacy import AccountDeactivationService

    AccountDeactivationService.deactivate(seeker.user, password='TestPass123!')

    assert authenticate(email=seeker.user.email, password='TestPass123!') is None


def test_cannot_deactivate_twice(seeker):
    from rest_framework.exceptions import ValidationError

    from apps.accounts.privacy import AccountDeactivationService

    AccountDeactivationService.deactivate(seeker.user, password='TestPass123!')

    with pytest.raises(ValidationError):
        AccountDeactivationService.deactivate(
            seeker.user, password='TestPass123!',
        )


def test_deactivation_is_audited(seeker):
    """The account closure itself has to leave a trace."""
    from apps.accounts.privacy import AccountDeactivationService
    from apps.audit.models import AuditLog

    AccountDeactivationService.deactivate(seeker.user, password='TestPass123!')

    entry = AuditLog.objects.filter(
        model_name='accounts.User', object_id=str(seeker.user.pk),
        action=AuditLog.Action.UPDATE,
    ).latest('created_at')
    assert entry.new_value.get('is_deleted') is True