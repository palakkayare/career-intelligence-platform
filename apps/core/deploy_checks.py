"""
Start-up checks for production settings.

Most settings have harmless development defaults: a blank pepper, Redis on
localhost. In production those defaults are wrong without crashing anything.
Salary IP hashes become reversible, Celery waits for a broker that is not
there, emails go nowhere. These checks turn each case into a start-up failure
that names the variable, so a half-configured deploy never goes live.

Plain values in, list of messages out, so it is testable without importing
production settings.
"""

from urllib.parse import urlparse

from cryptography.fernet import Fernet

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _points_nowhere(url):
    """True for a blank URL or one aimed at this container itself."""
    if not url:
        return True
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def production_config_errors(config):
    errors = []

    if not config.get("ALLOWED_HOSTS_FROM_ENV"):
        errors.append(
            "DJANGO_ALLOWED_HOSTS is empty. List the API domain(s), comma-separated, "
            "for example web-production-abc1.up.railway.app"
        )

    for name in ("DATABASE_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "REDIS_CACHE_URL"):
        if _points_nowhere(config.get(name, "")):
            errors.append(
                f"{name} is blank or points at localhost. Inside a container "
                "that is the container itself, not the database or Redis."
            )

    keys = [k.strip() for k in (config.get("FIELD_ENCRYPTION_KEY") or "").split(",") if k.strip()]
    if not keys:
        errors.append("FIELD_ENCRYPTION_KEY is not set. 2FA secrets cannot be stored without it.")
    else:
        for key in keys:
            try:
                Fernet(key)
            except (ValueError, TypeError):
                errors.append("FIELD_ENCRYPTION_KEY is not a valid Fernet key.")
                break

    if not config.get("SALARY_IP_PEPPER"):
        errors.append(
            "SALARY_IP_PEPPER is not set. Without it the stored IP hashes can be reversed."
        )

    if not config.get("SENDGRID_API_KEY"):
        errors.append("SENDGRID_API_KEY is not set. No email could be sent.")

    razorpay_key = config.get("RAZORPAY_KEY_ID") or ""
    if not razorpay_key:
        errors.append("RAZORPAY_KEY_ID is not set. Checkout would fail for every user.")
    else:
        for name in ("RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
            if not config.get(name):
                errors.append(f"{name} is not set.")

    if razorpay_key.startswith("rzp_live_") and not config.get("INVOICE_GSTIN"):
        errors.append(
            "INVOICE_GSTIN is not set. Live payments issue tax invoices, and an "
            "invoice without the GSTIN is not a valid one."
        )

    return errors
