"""
Step 32: 2FA secrets encrypted at rest, breached-password rejection.
"""

import hashlib
import importlib

import pytest
from cryptography.fernet import Fernet
from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection

from apps.accounts import validators
from apps.accounts.fields import DecryptionError, decrypt_str, encrypt_str, looks_encrypted
from apps.accounts.models import TwoFactorAuth
from apps.accounts.validators import BreachedPasswordValidator, breach_count

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


@pytest.fixture
def key(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return settings.FIELD_ENCRYPTION_KEY


# --------------------------------------------------------------------------
# Encryption primitives
# --------------------------------------------------------------------------


def test_round_trip(key):
    token = encrypt_str(SECRET)

    assert token != SECRET
    assert SECRET not in token
    assert looks_encrypted(token)
    assert decrypt_str(token) == SECRET


def test_the_same_secret_encrypts_differently_each_time(key):
    """No two users with the same secret can be spotted by comparing ciphertext."""
    assert encrypt_str(SECRET) != encrypt_str(SECRET)


def test_a_base32_secret_never_looks_encrypted():
    assert not looks_encrypted(SECRET)
    assert not looks_encrypted("")
    assert not looks_encrypted(None)


def test_a_missing_key_fails_loudly(settings):
    settings.FIELD_ENCRYPTION_KEY = ""

    with pytest.raises(ImproperlyConfigured, match="FIELD_ENCRYPTION_KEY is not set"):
        encrypt_str(SECRET)


def test_a_malformed_key_fails_loudly(settings):
    settings.FIELD_ENCRYPTION_KEY = "not-a-real-key"

    with pytest.raises(ImproperlyConfigured, match="not a valid Fernet key"):
        encrypt_str(SECRET)


def test_the_wrong_key_raises_instead_of_returning_empty(settings, key):
    """
    Regression guard: a decrypt that returns "" on failure turns a wrong key
    into every user's 2FA silently breaking.
    """
    token = encrypt_str(SECRET)
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()

    with pytest.raises(DecryptionError):
        decrypt_str(token)


def test_key_rotation_keeps_old_data_readable(settings, key):
    old_token = encrypt_str(SECRET)
    new_key = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEY = f"{new_key},{key}"

    assert decrypt_str(old_token) == SECRET

    settings.FIELD_ENCRYPTION_KEY = new_key
    new_token = encrypt_str(SECRET)
    assert decrypt_str(new_token) == SECRET


# --------------------------------------------------------------------------
# The model field
# --------------------------------------------------------------------------


def raw_secret(pk):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT secret FROM {TwoFactorAuth._meta.db_table} WHERE id = %s", [pk])
        return cursor.fetchone()[0]


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        email="twofa-encryption@test.com", password="Unused-Pass-9x!"
    )


def test_the_database_holds_ciphertext_and_the_model_holds_plaintext(key, user):
    twofa = TwoFactorAuth.objects.create(user=user, secret=SECRET)

    assert looks_encrypted(raw_secret(twofa.pk))
    assert SECRET not in raw_secret(twofa.pk)
    assert TwoFactorAuth.objects.get(pk=twofa.pk).secret == SECRET


def test_saving_again_does_not_double_encrypt(key, user):
    twofa = TwoFactorAuth.objects.create(user=user, secret=SECRET)

    reloaded = TwoFactorAuth.objects.get(pk=twofa.pk)
    reloaded.is_enabled = True
    reloaded.save()
    reloaded.save()

    assert TwoFactorAuth.objects.get(pk=twofa.pk).secret == SECRET


def test_queryset_update_is_encrypted_too(key, user):
    twofa = TwoFactorAuth.objects.create(user=user, secret="A" * 32)

    TwoFactorAuth.objects.filter(pk=twofa.pk).update(secret=SECRET)

    assert looks_encrypted(raw_secret(twofa.pk))
    assert TwoFactorAuth.objects.get(pk=twofa.pk).secret == SECRET


# --------------------------------------------------------------------------
# The data migration
# --------------------------------------------------------------------------

migration = importlib.import_module("apps.accounts.migrations.0006_encrypt_two_factor_secret")


class _Editor:
    connection = connection


def test_the_migration_encrypts_legacy_plaintext_and_can_reverse(key, user):
    twofa = TwoFactorAuth.objects.create(user=user, secret=SECRET)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {TwoFactorAuth._meta.db_table} SET secret = %s WHERE id = %s",
            [SECRET, twofa.pk],
        )

    migration.encrypt_existing_secrets(django_apps, _Editor())
    assert looks_encrypted(raw_secret(twofa.pk))
    assert TwoFactorAuth.objects.get(pk=twofa.pk).secret == SECRET

    migration.encrypt_existing_secrets(django_apps, _Editor())
    assert TwoFactorAuth.objects.get(pk=twofa.pk).secret == SECRET, "safe to re-run"

    migration.decrypt_existing_secrets(django_apps, _Editor())
    assert raw_secret(twofa.pk) == SECRET


# --------------------------------------------------------------------------
# Breached passwords
# --------------------------------------------------------------------------


def hibp_body_for(password, count=3):
    suffix = hashlib.sha1(password.encode()).hexdigest().upper()[5:]
    return "\r\n".join(
        [
            "0018A45C4D1DEF81644B54AB7F969B88D65:1",
            f"{suffix}:{count}",
            "FFFFF00000000000000000000000000000000:0",
        ]
    )


@pytest.fixture
def check_on(settings):
    settings.PASSWORD_BREACH_CHECK = True


def test_off_by_default_so_tests_and_development_never_call_out(monkeypatch):
    monkeypatch.setattr(validators, "fetch_range", lambda prefix: pytest.fail("called HIBP"))

    assert settings.PASSWORD_BREACH_CHECK is False
    BreachedPasswordValidator().validate("Password123")


def test_a_breached_password_is_rejected(check_on, monkeypatch):
    monkeypatch.setattr(validators, "fetch_range", lambda prefix: hibp_body_for("Password123"))

    with pytest.raises(ValidationError) as excinfo:
        BreachedPasswordValidator().validate("Password123")

    assert excinfo.value.error_list[0].code == "password_breached"


def test_an_unbreached_password_passes(check_on, monkeypatch):
    monkeypatch.setattr(validators, "fetch_range", lambda prefix: hibp_body_for("something-else"))

    BreachedPasswordValidator().validate("a-long-unique-passphrase-7Q")


def test_padding_entries_with_zero_count_do_not_count_as_breached(check_on, monkeypatch):
    monkeypatch.setattr(
        validators, "fetch_range", lambda prefix: hibp_body_for("Padded-Pass-1", count=0)
    )

    assert breach_count("Padded-Pass-1") == 0


def test_only_five_hash_characters_leave_the_server(check_on, monkeypatch):
    sent = []
    monkeypatch.setattr(validators, "fetch_range", lambda prefix: sent.append(prefix) or "")

    breach_count("Password123")

    full_hash = hashlib.sha1(b"Password123").hexdigest().upper()
    assert sent == [full_hash[:5]]
    assert "Password123" not in sent[0]


def test_an_unreachable_api_does_not_block_signups(check_on, monkeypatch):
    def down(prefix):
        raise OSError("network unreachable")

    monkeypatch.setattr(validators, "fetch_range", down)

    BreachedPasswordValidator().validate("Password123")


def test_django_password_validation_includes_the_breach_check(check_on, monkeypatch):
    """Registration and password reset both go through validate_password."""
    monkeypatch.setattr(validators, "fetch_range", lambda prefix: hibp_body_for("Tr0ub4dor&3xyz"))

    with pytest.raises(ValidationError):
        validate_password("Tr0ub4dor&3xyz")


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------


def test_the_frontend_can_read_the_request_id_header():
    """Browsers hide response headers from JavaScript unless CORS exposes them."""
    assert "X-Request-ID" in settings.CORS_EXPOSE_HEADERS
