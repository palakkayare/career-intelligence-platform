"""
Authentication services: OTP, two-factor, and pending-login tokens.

This is the security-critical half of the accounts app and it sat at 36%
coverage. Everything here guards account access, so the tests care less
about happy paths and more about what happens when someone is trying.
"""
from datetime import timedelta
from unittest.mock import patch

import pyotp
import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError

from apps.accounts.models import BackupCode, OTPCode, TwoFactorAuth, User
from apps.accounts.services import (
    OTPService,
    PendingAuthService,
    TwoFactorAuthService,
)

pytestmark = pytest.mark.django_db


def age_otp(otp, seconds):
    """Backdate an OTP so cooldown and expiry can be exercised."""
    OTPCode.objects.filter(pk=otp.pk).update(
        created_at=timezone.now() - timedelta(seconds=seconds),
    )
    otp.refresh_from_db()
    return otp


# --------------------------------------------------------------------------
# OTP: issuing
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_an_otp_is_created_and_emailed(seeker_user):
    """Regression: accounts/services.py was at 36% coverage."""
    mail.outbox = []

    otp = OTPService.create_and_send(seeker_user)

    assert len(otp.code) == 6
    assert otp.code.isdigit()
    assert otp.is_used is False
    assert len(mail.outbox) == 1
    assert seeker_user.email in mail.outbox[0].to


def test_the_code_is_not_in_the_database_in_a_guessable_order(seeker_user):
    """Codes come from secrets, not a counter or the clock."""
    codes = set()
    for _ in range(5):
        otp = OTPService.create_and_send(seeker_user)
        codes.add(otp.code)
        age_otp(otp, OTPService.RESEND_COOLDOWN_SECONDS + 1)

    assert len(codes) > 1, 'five identical codes means the generator is broken'


def test_requesting_a_second_code_too_soon_is_refused(seeker_user):
    OTPService.create_and_send(seeker_user)

    with pytest.raises(ValidationError):
        OTPService.create_and_send(seeker_user)


def test_a_new_code_is_allowed_after_the_cooldown(seeker_user):
    first = OTPService.create_and_send(seeker_user)
    age_otp(first, OTPService.RESEND_COOLDOWN_SECONDS + 1)

    second = OTPService.create_and_send(seeker_user)

    assert second.pk != first.pk


@pytest.mark.regression
def test_issuing_a_new_code_invalidates_the_old_one(seeker_user):
    """
    Two live codes would double an attacker's guessing surface and let a
    leaked older code keep working.
    """
    first = OTPService.create_and_send(seeker_user)
    age_otp(first, OTPService.RESEND_COOLDOWN_SECONDS + 1)

    OTPService.create_and_send(seeker_user)
    first.refresh_from_db()

    assert first.is_used is True


def test_codes_for_different_purposes_do_not_collide(seeker_user):
    """A 2FA code must not satisfy email verification."""
    OTPService.create_and_send(seeker_user, OTPCode.Purpose.EMAIL_VERIFICATION)
    twofa = OTPService.create_and_send(seeker_user, OTPCode.Purpose.TWO_FA)

    with pytest.raises(ValidationError):
        OTPService.verify(
            seeker_user, twofa.code, OTPCode.Purpose.EMAIL_VERIFICATION,
        )


# --------------------------------------------------------------------------
# OTP: verifying
# --------------------------------------------------------------------------

def test_the_right_code_verifies_and_is_consumed(seeker_user):
    otp = OTPService.create_and_send(seeker_user)

    OTPService.verify(seeker_user, otp.code)
    otp.refresh_from_db()

    assert otp.is_used is True


def test_a_consumed_code_cannot_be_replayed(seeker_user):
    otp = OTPService.create_and_send(seeker_user)
    OTPService.verify(seeker_user, otp.code)

    with pytest.raises(ValidationError):
        OTPService.verify(seeker_user, otp.code)


def test_a_wrong_code_is_rejected(seeker_user):
    OTPService.create_and_send(seeker_user)

    with pytest.raises(ValidationError):
        OTPService.verify(seeker_user, '000000')


def test_verifying_without_a_code_outstanding_fails(seeker_user):
    with pytest.raises(ValidationError):
        OTPService.verify(seeker_user, '123456')


def test_an_expired_code_is_rejected(seeker_user):
    otp = OTPService.create_and_send(seeker_user)
    OTPCode.objects.filter(pk=otp.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    with pytest.raises(ValidationError):
        OTPService.verify(seeker_user, otp.code)


@pytest.mark.regression
def test_brute_force_is_cut_off_after_three_attempts(seeker_user):
    """
    A six-digit code is only a million guesses. The attempt cap is what
    makes it safe, so it has to hold even when the fourth guess is right.
    """
    otp = OTPService.create_and_send(seeker_user)

    for _ in range(3):
        with pytest.raises(ValidationError):
            OTPService.verify(seeker_user, '000000')

    with pytest.raises(ValidationError):
        OTPService.verify(seeker_user, otp.code)

    otp.refresh_from_db()
    assert otp.is_used is True, 'the code should be burned, not just refused'


def test_failed_attempts_are_counted(seeker_user):
    otp = OTPService.create_and_send(seeker_user)

    with pytest.raises(ValidationError):
        OTPService.verify(seeker_user, '000000')

    otp.refresh_from_db()
    assert otp.attempts == 1


def test_one_users_code_does_not_work_for_another(seeker_user, recruiter_user):
    otp = OTPService.create_and_send(seeker_user)

    with pytest.raises(ValidationError):
        OTPService.verify(recruiter_user, otp.code)


# --------------------------------------------------------------------------
# Two-factor: setup
# --------------------------------------------------------------------------

def test_setup_returns_a_qr_code_and_a_manual_secret(seeker_user):
    from urllib.parse import unquote

    result = TwoFactorAuthService.initiate_setup(seeker_user)

    assert result['qr_code'].startswith('data:image/png;base64,')
    assert result['secret_text']
    # The URI is percent-encoded, so decode before looking for the address
    assert seeker_user.email in unquote(result['provisioning_uri'])
    assert result['provisioning_uri'].startswith('otpauth://totp/')

def test_setup_alone_does_not_enable_2fa(seeker_user):
    """The user has to prove their authenticator works first."""
    TwoFactorAuthService.initiate_setup(seeker_user)

    assert seeker_user.two_factor.is_enabled is False
    assert seeker_user.is_2fa_enabled is False


def test_a_correct_code_enables_2fa_and_returns_backup_codes(seeker_user):
    setup = TwoFactorAuthService.initiate_setup(seeker_user)
    code = pyotp.TOTP(setup['secret_text']).now()

    backup_codes = TwoFactorAuthService.verify_and_enable(seeker_user, code)

    seeker_user.refresh_from_db()
    assert seeker_user.is_2fa_enabled is True
    assert len(backup_codes) == TwoFactorAuthService.BACKUP_CODE_COUNT


def test_a_wrong_code_does_not_enable_2fa(seeker_user):
    TwoFactorAuthService.initiate_setup(seeker_user)

    with pytest.raises(ValidationError):
        TwoFactorAuthService.verify_and_enable(seeker_user, '000000')

    seeker_user.refresh_from_db()
    assert seeker_user.is_2fa_enabled is False


def test_enabling_without_setup_is_refused(seeker_user):
    with pytest.raises(ValidationError):
        TwoFactorAuthService.verify_and_enable(seeker_user, '123456')


def test_2fa_cannot_be_enabled_twice(seeker_user):
    setup = TwoFactorAuthService.initiate_setup(seeker_user)
    code = pyotp.TOTP(setup['secret_text']).now()
    TwoFactorAuthService.verify_and_enable(seeker_user, code)

    with pytest.raises(ValidationError):
        TwoFactorAuthService.verify_and_enable(seeker_user, code)


# --------------------------------------------------------------------------
# Two-factor: login
# --------------------------------------------------------------------------

@pytest.fixture
def user_with_2fa(seeker_user):
    """A user with 2FA enabled. Returns (user, secret, backup_codes)."""
    setup = TwoFactorAuthService.initiate_setup(seeker_user)
    secret = setup['secret_text']
    codes = TwoFactorAuthService.verify_and_enable(
        seeker_user, pyotp.TOTP(secret).now(),
    )
    return seeker_user, secret, codes


def test_a_current_totp_code_is_accepted(user_with_2fa):
    user, secret, _ = user_with_2fa

    assert TwoFactorAuthService.verify_login_code(user, pyotp.TOTP(secret).now())


def test_a_wrong_totp_code_is_rejected(user_with_2fa):
    user, _, _ = user_with_2fa

    assert TwoFactorAuthService.verify_login_code(user, '000000') is False


@pytest.mark.parametrize('bad', ['', 'abcdef', '12345', '1234567', None])
def test_malformed_codes_are_rejected_without_crashing(user_with_2fa, bad):
    user, _, _ = user_with_2fa

    assert TwoFactorAuthService.verify_login_code(user, bad) is False


def test_a_backup_code_works_when_the_phone_does_not(user_with_2fa):
    user, _, codes = user_with_2fa

    assert TwoFactorAuthService.verify_login_code(user, codes[0]) is True


@pytest.mark.regression
def test_a_backup_code_only_works_once(user_with_2fa):
    """
    Backup codes are written down on paper. Single use is what limits the
    damage when that paper is seen by someone else.
    """
    user, _, codes = user_with_2fa

    assert TwoFactorAuthService.verify_login_code(user, codes[0]) is True
    assert TwoFactorAuthService.verify_login_code(user, codes[0]) is False


def test_backup_codes_are_stored_hashed(user_with_2fa):
    """A database leak must not hand over working codes."""
    user, _, codes = user_with_2fa

    stored = set(BackupCode.objects.filter(user=user).values_list(
        'code_hash', flat=True,
    ))

    assert not stored & set(codes)


def test_login_codes_are_refused_when_2fa_is_off(seeker_user):
    assert TwoFactorAuthService.verify_login_code(seeker_user, '123456') is False


# --------------------------------------------------------------------------
# Two-factor: management
# --------------------------------------------------------------------------

def test_disabling_2fa_requires_the_password(user_with_2fa):
    user, _, _ = user_with_2fa

    with pytest.raises(ValidationError):
        TwoFactorAuthService.disable(user, 'wrong-password')

    user.refresh_from_db()
    assert user.is_2fa_enabled is True


def test_disabling_2fa_clears_the_backup_codes(user_with_2fa):
    user, _, _ = user_with_2fa

    TwoFactorAuthService.disable(user, 'TestPass123!')

    user.refresh_from_db()
    assert user.is_2fa_enabled is False
    assert not TwoFactorAuth.objects.filter(user=user).exists()
    assert not BackupCode.objects.filter(user=user).exists()


def test_regenerating_replaces_every_old_code(user_with_2fa):
    user, _, old_codes = user_with_2fa

    new_codes = TwoFactorAuthService.regenerate_backup_codes(user)

    assert set(new_codes) & set(old_codes) == set()
    assert TwoFactorAuthService.verify_login_code(user, old_codes[0]) is False
    assert TwoFactorAuthService.verify_login_code(user, new_codes[0]) is True


def test_regenerating_without_2fa_is_refused(seeker_user):
    with pytest.raises(ValidationError):
        TwoFactorAuthService.regenerate_backup_codes(seeker_user)


# --------------------------------------------------------------------------
# Pending login token
# --------------------------------------------------------------------------

def test_a_pending_token_round_trips_to_the_same_user(seeker_user):
    token = PendingAuthService.create_token(seeker_user)

    assert PendingAuthService.verify_token(token) == seeker_user


@pytest.mark.regression
def test_a_tampered_pending_token_is_rejected(seeker_user, recruiter_user):
    """
    This token is what stands between step one and step two of a 2FA login.
    If it could be edited, 2FA would be bypassable by swapping the user id.
    """
    token = PendingAuthService.create_token(seeker_user)
    forged = token.replace(str(seeker_user.id), str(recruiter_user.id), 1)

    with pytest.raises(AuthenticationFailed):
        PendingAuthService.verify_token(forged)


def test_an_expired_pending_token_is_rejected(seeker_user):
    from django.core.signing import SignatureExpired

    token = PendingAuthService.create_token(seeker_user)

    with patch(
        'django.core.signing.TimestampSigner.unsign',
        side_effect=SignatureExpired('too old'),
    ):
        with pytest.raises(AuthenticationFailed):
            PendingAuthService.verify_token(token)


def test_a_pending_token_for_a_deactivated_user_is_rejected(seeker_user):
    token = PendingAuthService.create_token(seeker_user)
    seeker_user.is_active = False
    seeker_user.save(update_fields=['is_active'])

    with pytest.raises(AuthenticationFailed):
        PendingAuthService.verify_token(token)


def test_garbage_is_rejected():
    with pytest.raises(AuthenticationFailed):
        PendingAuthService.verify_token('not-a-real-token')