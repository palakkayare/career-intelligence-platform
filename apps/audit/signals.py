"""
Signal handlers that write the audit trail.

Only models listed in settings.AUDITED_MODELS are watched. Auditing every
model would double the write load and bury the interesting rows, so the list
is deliberately short and explicit.
"""

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .context import get_context
from .models import AuditLog

logger = logging.getLogger(__name__)

# Never recorded, whatever model they appear on.
SENSITIVE_FIELDS = {
    "password",
    "secret",
    "token",
    "code_hash",
    "razorpay_signature",
    "signature",
    "fcm_token",
    "google_sub",
}

# Noise: these change on nearly every save and say nothing useful.
IGNORED_FIELDS = {"updated_at", "last_login", "search_vector"}


def _serialise(value):
    """Coerce a field value into something JSONField can store."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _snapshot(instance):
    """Concrete, non-sensitive field values as a plain dict."""
    data = {}
    for field in instance._meta.concrete_fields:
        name = field.name
        if name in IGNORED_FIELDS or name in SENSITIVE_FIELDS:
            continue
        data[name] = _serialise(getattr(instance, field.attname, None))
    return data


def _label(instance):
    return f"{instance._meta.app_label}.{instance._meta.object_name}"


def _is_audited(instance):
    return _label(instance) in set(getattr(settings, "AUDITED_MODELS", []))


def _write(instance, action, old_value=None, new_value=None):
    """
    Persist one entry. Audit failures must never break the operation being
    audited, so everything is swallowed and logged.
    """
    ctx = get_context()
    user = ctx["user"]
    try:
        AuditLog.objects.create(
            user=user,
            user_email=getattr(user, "email", "") or "",
            action=action,
            model_name=_label(instance),
            object_id=str(instance.pk),
            object_repr=str(instance)[:255],
            old_value=old_value or {},
            new_value=new_value or {},
            ip_address=ctx["ip_address"],
            user_agent=ctx["user_agent"],
        )
    except Exception:
        logger.exception("Failed to write audit log for %s", _label(instance))


@receiver(pre_save)
def capture_previous_state(sender, instance, **kwargs):
    """
    Stash the pre-change row so post_save can diff against it. Costs one extra
    query, which is why the audited-model list is kept small.
    """
    if not _is_audited(instance) or instance.pk is None:
        return

    manager = getattr(sender, "all_objects", sender._default_manager)
    try:
        instance._audit_previous = _snapshot(manager.get(pk=instance.pk))
    except sender.DoesNotExist:
        instance._audit_previous = None
    except Exception:
        instance._audit_previous = None


@receiver(post_save)
def record_create_or_update(sender, instance, created, **kwargs):
    if not _is_audited(instance):
        return

    if created:
        _write(instance, AuditLog.Action.CREATE, new_value=_snapshot(instance))
        return

    previous = getattr(instance, "_audit_previous", None)
    if previous is None:
        return

    current = _snapshot(instance)
    old_diff = {k: v for k, v in previous.items() if current.get(k) != v}
    new_diff = {k: current[k] for k in old_diff if k in current}

    # A save that changed nothing is not worth a row.
    if not old_diff:
        return

    _write(instance, AuditLog.Action.UPDATE, old_value=old_diff, new_value=new_diff)


@receiver(post_delete)
def record_delete(sender, instance, **kwargs):
    """
    Hard deletes only. A soft delete is a save, so it arrives as an UPDATE
    showing is_deleted flipping to True - which is the more useful record.
    """
    if not _is_audited(instance):
        return
    _write(instance, AuditLog.Action.DELETE, old_value=_snapshot(instance))
