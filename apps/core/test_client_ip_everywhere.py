"""
Every client IP in the codebase comes from apps/core/client_ip.py.
"""

from pathlib import Path

from django.test import RequestFactory, override_settings

from apps.audit.middleware import _client_ip as audit_client_ip
from apps.career_intel.salary_services import client_ip as salary_client_ip

APPS_DIR = Path(__file__).resolve().parents[1]

rf = RequestFactory()


def forged(**extra):
    return rf.post("/", REMOTE_ADDR="198.51.100.1", HTTP_X_FORWARDED_FOR="6.6.6.6", **extra)


def test_nothing_else_reads_x_forwarded_for_directly():
    """
    Regression guard. Four copies of the same forgeable parser were found in
    one pass; this keeps a fifth from appearing.
    """
    offenders = []
    for path in APPS_DIR.rglob("*.py"):
        rel = path.relative_to(APPS_DIR).as_posix()
        if "migrations/" in rel or path.name.startswith(("test", "conftest")):
            continue
        if rel == "core/client_ip.py":
            continue
        if "HTTP_X_FORWARDED_FOR" in path.read_text():
            offenders.append(rel)

    assert offenders == [], f"use apps.core.client_ip.client_ip instead: {offenders}"


@override_settings(TRUSTED_PROXY_COUNT=0)
def test_salary_limits_ignore_a_forged_header():
    """A made-up address per request used to walk past the per-IP submission limit."""
    assert salary_client_ip(forged()) == "198.51.100.1"


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_salary_uses_the_proxy_appended_address():
    request = rf.post("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.50")

    assert salary_client_ip(request) == "203.0.113.50"


def test_salary_still_accepts_no_request():
    assert salary_client_ip(None) is None


@override_settings(TRUSTED_PROXY_COUNT=0)
def test_the_audit_trail_records_the_real_address_not_the_claimed_one():
    assert audit_client_ip(forged()) == "198.51.100.1"


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_the_audit_trail_uses_the_proxy_appended_address():
    request = rf.post("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.50")

    assert audit_client_ip(request) == "203.0.113.50"
