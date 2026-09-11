"""
Field-level encryption for secrets that must be readable, not just checkable.

Passwords and backup codes are hashed: the platform only ever needs to check
them. A TOTP secret is different - producing the expected code needs the
secret itself - so it cannot be hashed and is encrypted instead.

Fernet (AES-128-CBC with HMAC-SHA256) from `cryptography`. The key comes from
the FIELD_ENCRYPTION_KEY environment variable, never from the database it
protects. A leaked database backup alone no longer gives away anyone's 2FA.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

# Every Fernet token starts with the version byte 0x80 and a timestamp, which
# base64-encode to this. A Base32 TOTP secret uses only A-Z and 2-7, so it can
# never start this way.
FERNET_PREFIX = "gAAAAA"


class DecryptionError(Exception):
    """A stored value could not be decrypted with any configured key."""


@lru_cache(maxsize=4)
def _fernet_for(raw_keys):
    keys = [key.strip() for key in raw_keys.split(",") if key.strip()]
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with: python -c "
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        # The first key encrypts; every key can decrypt. Rotating means putting
        # the new key first and keeping the old one until data is re-saved.
        return MultiFernet([Fernet(key) for key in keys])
    except ValueError as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64 bytes)."
        ) from exc


def _fernet():
    return _fernet_for(getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "")


def encrypt_str(plaintext):
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_str(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        # Deliberately loud. Quietly returning "" would turn a wrong key into
        # every user's 2FA silently breaking - or, for a careless caller,
        # silently passing.
        raise DecryptionError(
            "Stored value could not be decrypted: FIELD_ENCRYPTION_KEY is wrong, "
            "or a key was removed while data encrypted with it remained."
        ) from exc


def looks_encrypted(value):
    return isinstance(value, str) and value.startswith(FERNET_PREFIX)


class EncryptedTextField(models.TextField):
    """
    Encrypted in the database, plain text in Python.

    Code reads and assigns ordinary strings and never sees ciphertext, which
    is also why a value can never be encrypted twice. Filtering on the value
    cannot match anything: every encryption is randomised.
    """

    description = "Text encrypted at rest"

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        return decrypt_str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return encrypt_str(value)
