"""
Production start-up checks.
"""

import pytest
from cryptography.fernet import Fernet

from apps.core.deploy_checks import production_config_errors


def complete_config(**overrides):
    config = {
        "ALLOWED_HOSTS_FROM_ENV": ["api.example.com"],
        "DATABASE_URL": "postgres://u:p@ep-cool.ap-southeast-1.aws.neon.tech/db?sslmode=require",
        "CELERY_BROKER_URL": "redis://default:p@redis.railway.internal:6379/1",
        "CELERY_RESULT_BACKEND": "redis://default:p@redis.railway.internal:6379/2",
        "REDIS_CACHE_URL": "redis://default:p@redis.railway.internal:6379/3",
        "FIELD_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SALARY_IP_PEPPER": "pepper",
        "SENDGRID_API_KEY": "SG.key",
        "RAZORPAY_KEY_ID": "rzp_test_abc",
        "RAZORPAY_KEY_SECRET": "secret",
        "RAZORPAY_WEBHOOK_SECRET": "whsecret",
        "INVOICE_GSTIN": "",
    }
    config.update(overrides)
    return config


def test_a_complete_pre_launch_config_passes():
    assert production_config_errors(complete_config()) == []


def test_every_problem_is_reported_at_once():
    """Six missing variables should cost one failed deploy, not six."""
    errors = production_config_errors({})

    assert len(errors) >= 8


@pytest.mark.parametrize("name", ["DATABASE_URL", "CELERY_BROKER_URL", "REDIS_CACHE_URL"])
@pytest.mark.parametrize("url", ["", "redis://localhost:6379/1", "postgres://u:p@127.0.0.1/db"])
def test_localhost_urls_are_rejected(name, url):
    """The base.py defaults point at localhost, which in a container is nothing."""
    errors = production_config_errors(complete_config(**{name: url}))

    assert any(error.startswith(name) for error in errors)


def test_allowed_hosts_must_come_from_the_environment():
    errors = production_config_errors(complete_config(ALLOWED_HOSTS_FROM_ENV=[]))

    assert any("DJANGO_ALLOWED_HOSTS" in error for error in errors)


@pytest.mark.parametrize("value", ["", "not-a-fernet-key"])
def test_the_encryption_key_must_be_present_and_valid(value):
    errors = production_config_errors(complete_config(FIELD_ENCRYPTION_KEY=value))

    assert any("FIELD_ENCRYPTION_KEY" in error for error in errors)


def test_a_rotation_list_of_valid_keys_passes():
    keys = f"{Fernet.generate_key().decode()},{Fernet.generate_key().decode()}"

    assert production_config_errors(complete_config(FIELD_ENCRYPTION_KEY=keys)) == []


@pytest.mark.parametrize("name", ["SALARY_IP_PEPPER", "SENDGRID_API_KEY", "RAZORPAY_KEY_ID"])
def test_required_secrets(name):
    errors = production_config_errors(complete_config(**{name: ""}))

    assert any(error.startswith(name) for error in errors)


def test_razorpay_secrets_are_required_alongside_the_key():
    errors = production_config_errors(complete_config(RAZORPAY_WEBHOOK_SECRET=""))

    assert errors == ["RAZORPAY_WEBHOOK_SECRET is not set."]


def test_test_keys_do_not_need_a_gstin():
    assert production_config_errors(complete_config(INVOICE_GSTIN="")) == []


def test_live_keys_need_a_gstin():
    errors = production_config_errors(complete_config(RAZORPAY_KEY_ID="rzp_live_abc"))

    assert any("INVOICE_GSTIN" in error for error in errors)

    with_gstin = complete_config(RAZORPAY_KEY_ID="rzp_live_abc", INVOICE_GSTIN="29ABCDE1234F1Z5")
    assert production_config_errors(with_gstin) == []
