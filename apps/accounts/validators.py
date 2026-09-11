"""
Reject passwords that appear in known data breaches.

Uses the Have I Been Pwned range API with k-anonymity: only the first five
characters of the password's SHA-1 hash leave the server, and the match is
made here against the suffixes that come back. Neither the password nor its
full hash is ever sent.

Registered in AUTH_PASSWORD_VALIDATORS, so it covers registration, password
reset and anything else that calls Django's validate_password.
"""

import hashlib
import logging
import urllib.request

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
TIMEOUT_SECONDS = 2


def fetch_range(prefix):
    """The 'SUFFIX:COUNT' lines HIBP holds for a five-character hash prefix."""
    request = urllib.request.Request(
        RANGE_URL.format(prefix=prefix),
        headers={
            "User-Agent": "career-intelligence-platform",
            # Pads the response with fake zero-count entries, so its size
            # does not hint at which prefix was asked for.
            "Add-Padding": "true",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def breach_count(password):
    """Times the password appears in known breaches; 0 if absent or unknown."""
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]

    try:
        body = fetch_range(prefix)
    except (OSError, ValueError):
        # Fail open. Blocking every signup while a third party is down is
        # worse than occasionally letting a breached password through.
        logger.warning("password_breach_check_unavailable", exc_info=True)
        return 0

    for line in body.splitlines():
        candidate, _sep, count = line.partition(":")
        if candidate.strip() == suffix:
            try:
                return int(count.strip())
            except ValueError:
                return 0
    return 0


class BreachedPasswordValidator:
    """
    Off unless PASSWORD_BREACH_CHECK is true, so development and the test
    suite never call a third-party API. Production switches it on.
    """

    def validate(self, password, user=None):
        if not getattr(settings, "PASSWORD_BREACH_CHECK", False) or not password:
            return
        if breach_count(password) > 0:
            raise ValidationError(
                "This password has appeared in a known data breach. "
                "Please choose a different one.",
                code="password_breached",
            )

    def get_help_text(self):
        return "Your password must not appear in a known data breach."
