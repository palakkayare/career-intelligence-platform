"""
Log formatting: JSON in production, readable text in development.

Every line carries the id of the request that produced it, so one failing
request can be pulled out of thousands of interleaved log lines.

Built on the standard library rather than python-json-logger: the formatter
is thirty lines, and a dependency for it is not worth carrying.
"""

import contextvars
import json
import logging
from datetime import datetime, timezone

from .observability import _scrub

# Set by RequestIdMiddleware for the life of one request. A context variable
# rather than a thread-local, so it stays correct under async views too.
request_id_var = contextvars.ContextVar("request_id", default="")

# Attributes every LogRecord has. Anything else on a record came from
# `extra=` and belongs in the JSON output.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "request_id",
}


class RequestIdFilter(logging.Filter):
    """Stamp the current request id onto every record ('-' outside a request)."""

    def filter(self, record):
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for a log aggregator to parse."""

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
        }

        extras = {key: value for key, value in vars(record).items() if key not in _STANDARD_ATTRS}
        # The same rules as Sentry: a password passed in `extra=` by mistake
        # should not end up in a log file either.
        payload.update(_scrub(extras))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def build_logging(json_output=False, level="INFO"):
    """The LOGGING dict for settings."""
    if json_output:
        formatter = {"()": "apps.core.log_format.JsonFormatter"}
    else:
        formatter = {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"}

    loggers = {
        # Django's own console handler would print every django.* line twice
        # alongside the root handler. Clear it and let records reach root.
        "django": {"handlers": [], "level": "INFO", "propagate": True},
        "django.db.backends": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
        "botocore": {"level": "WARNING"},
        "boto3": {"level": "WARNING"},
    }
    if not json_output:
        # runserver already prints one line per request in development.
        loggers["apps.core.requests"] = {"level": "WARNING"}

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "apps.core.log_format.RequestIdFilter"},
        },
        "formatters": {"default": formatter},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "filters": ["request_id"],
                "formatter": "default",
            },
        },
        "root": {"handlers": ["console"], "level": level},
        "loggers": loggers,
    }
