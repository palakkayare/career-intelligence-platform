"""
Step 31: tracing sample rates, request ids, JSON logs and Sentry user context.
"""

import json
import logging
import sys
import uuid
from types import SimpleNamespace

import pytest
import sentry_sdk
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.core import authentication as auth_module
from apps.core import observability
from apps.core.authentication import ObservedJWTAuthentication
from apps.core.log_format import JsonFormatter, RequestIdFilter, build_logging, request_id_var
from apps.core.middleware import RequestIdMiddleware, incoming_request_id
from apps.core.observability import before_send, init_sentry, make_traces_sampler, tag_user

rf = RequestFactory()


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------


def wsgi(path):
    return {"wsgi_environ": {"PATH_INFO": path}}


def test_health_checks_are_never_traced():
    """The load balancer polls these; tracing them spends the quota on nothing."""
    sampler = make_traces_sampler(0.1)

    assert sampler(wsgi("/api/v1/health/")) == 0.0
    assert sampler(wsgi("/api/v1/health/ready/")) == 0.0


def test_money_paths_are_always_traced():
    sampler = make_traces_sampler(0.1)

    assert sampler(wsgi("/api/v1/payments/verify/")) == 1.0
    assert sampler(wsgi("/api/v1/subscriptions/me/")) == 1.0
    assert sampler(wsgi("/api/v1/webhooks/razorpay/")) == 1.0


def test_login_is_sampled_like_everything_else():
    """Login is the busiest endpoint; 100% there would burn the free tier."""
    sampler = make_traces_sampler(0.1)

    assert sampler(wsgi("/api/v1/auth/login/")) == 0.1
    assert sampler(wsgi("/api/v1/jobs/")) == 0.1


def test_an_incoming_trace_header_cannot_force_sampling():
    """Any client can send sentry-trace; honouring it would let anyone spend the quota."""
    sampler = make_traces_sampler(0.1)

    context = {**wsgi("/api/v1/jobs/"), "parent_sampled": True}
    assert sampler(context) == 0.1


def test_asgi_and_non_http_contexts_are_handled():
    sampler = make_traces_sampler(0.1)

    assert sampler({"asgi_scope": {"path": "/api/v1/health/"}}) == 0.0
    assert sampler({"celery_job": {"task": "x"}}) == 0.1


def capture_init(monkeypatch):
    calls = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.update(kwargs))
    return calls


def test_a_zero_rate_turns_tracing_off_entirely(monkeypatch):
    """0 must mean off - not 'off except payments'."""
    calls = capture_init(monkeypatch)

    init_sentry(dsn="https://k@o0.ingest.sentry.io/0", environment="test", traces_sample_rate=0)

    assert "traces_sampler" not in calls
    assert "traces_sample_rate" not in calls


def test_a_positive_rate_installs_the_path_sampler(monkeypatch):
    calls = capture_init(monkeypatch)

    init_sentry(dsn="https://k@o0.ingest.sentry.io/0", environment="test", traces_sample_rate=0.2)

    assert calls["traces_sampler"](wsgi("/api/v1/jobs/")) == 0.2
    assert calls["traces_sampler"](wsgi("/api/v1/health/")) == 0.0


def test_performance_transactions_are_scrubbed_too(monkeypatch):
    """
    Regression: before_send only runs on error events. Transactions carry
    request data as well, and went out unscrubbed.
    """
    calls = capture_init(monkeypatch)

    init_sentry(dsn="https://k@o0.ingest.sentry.io/0", environment="test", traces_sample_rate=0.1)

    assert calls["before_send_transaction"] is before_send


# --------------------------------------------------------------------------
# Sentry user context
# --------------------------------------------------------------------------


@pytest.fixture
def active_sentry(monkeypatch):
    recorded = {"user": None, "tags": {}}
    monkeypatch.setattr(sentry_sdk, "get_client", lambda: SimpleNamespace(is_active=lambda: True))
    monkeypatch.setattr(sentry_sdk, "set_user", lambda user: recorded.update(user=user))
    monkeypatch.setattr(
        sentry_sdk, "set_tag", lambda key, value: recorded["tags"].__setitem__(key, value)
    )
    return recorded


def test_sentry_gets_the_user_id_and_role_but_never_the_email(active_sentry):
    user = SimpleNamespace(pk=42, role="seeker", email="priya@test.com", first_name="Priya")

    tag_user(user)

    assert active_sentry["user"] == {"id": "42"}
    assert active_sentry["tags"] == {"user_role": "seeker"}
    assert "priya" not in json.dumps(active_sentry).lower()


def test_nothing_is_tagged_when_sentry_is_not_running(monkeypatch):
    """Without a DSN the SDK scope is process-wide; writing to it would leak between requests."""
    monkeypatch.setattr(sentry_sdk, "get_client", lambda: SimpleNamespace(is_active=lambda: False))
    monkeypatch.setattr(sentry_sdk, "set_user", lambda user: pytest.fail("should not tag"))

    tag_user(SimpleNamespace(pk=1, role="seeker"))


def test_a_missing_sdk_is_tolerated(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)

    tag_user(SimpleNamespace(pk=1, role="seeker"))
    observability.tag_request("abc")


def test_jwt_authentication_tags_the_authenticated_user(monkeypatch):
    user = SimpleNamespace(pk=7, role="recruiter")
    tagged = []
    monkeypatch.setattr(JWTAuthentication, "authenticate", lambda self, request: (user, "tok"))
    monkeypatch.setattr(auth_module, "tag_user", tagged.append)

    result = ObservedJWTAuthentication().authenticate(rf.get("/"))

    assert result == (user, "tok")
    assert tagged == [user]


def test_anonymous_requests_are_not_tagged(monkeypatch):
    tagged = []
    monkeypatch.setattr(JWTAuthentication, "authenticate", lambda self, request: None)
    monkeypatch.setattr(auth_module, "tag_user", tagged.append)

    assert ObservedJWTAuthentication().authenticate(rf.get("/")) is None
    assert tagged == []


def test_the_api_uses_the_observed_authentication():
    classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]

    assert "apps.core.authentication.ObservedJWTAuthentication" in classes
    assert "rest_framework_simplejwt.authentication.JWTAuthentication" not in classes


# --------------------------------------------------------------------------
# Request ids
# --------------------------------------------------------------------------


def run_middleware(request, view=None):
    seen = {}

    def get_response(req):
        seen["during"] = request_id_var.get()
        return view(req) if view else HttpResponse("ok")

    response = RequestIdMiddleware(get_response)(request)
    return response, seen


def test_every_response_carries_a_request_id():
    response, _ = run_middleware(rf.get("/api/v1/jobs/"))

    assert uuid.UUID(response["X-Request-ID"])


def test_the_id_is_visible_while_the_view_runs_and_cleared_after():
    """This is what puts the same id on every log line of one request."""
    response, seen = run_middleware(rf.get("/api/v1/jobs/"))

    assert seen["during"] == response["X-Request-ID"]
    assert request_id_var.get() == ""


def test_the_id_is_cleared_even_when_the_view_raises():
    def boom(request):
        raise RuntimeError("view failed")

    with pytest.raises(RuntimeError):
        run_middleware(rf.get("/"), view=boom)

    assert request_id_var.get() == ""


def test_a_proxy_supplied_uuid_is_kept():
    incoming = str(uuid.uuid4())

    response, _ = run_middleware(rf.get("/", HTTP_X_REQUEST_ID=incoming))

    assert response["X-Request-ID"] == incoming


@pytest.mark.parametrize(
    "header",
    [
        "not-a-uuid",
        "x" * 5000,
        'abc\n{"level": "CRITICAL"}',
        "",
    ],
)
def test_a_forged_or_junk_header_is_replaced(header):
    """The header is client-controlled; only a real UUID gets into the logs."""
    request = rf.get("/", HTTP_X_REQUEST_ID=header)

    assert incoming_request_id(request) is None
    response, _ = run_middleware(request)
    assert response["X-Request-ID"] != header
    assert uuid.UUID(response["X-Request-ID"])


def test_the_completion_log_records_the_route_not_the_raw_path(caplog):
    """Raw paths carry unsubscribe tokens and profile ids."""

    def view(request):
        request.resolver_match = SimpleNamespace(route="unsubscribe/<str:token>/")
        return HttpResponse(status=200)

    with caplog.at_level(logging.INFO, logger="apps.core.requests"):
        run_middleware(rf.get("/unsubscribe/secret-token-abc/"), view=view)

    record = next(r for r in caplog.records if r.getMessage() == "request_completed")
    assert record.route == "unsubscribe/<str:token>/"
    assert record.status_code == 200
    assert record.user_id is None
    assert "secret-token-abc" not in json.dumps(vars(record), default=str)


def test_request_ids_are_the_first_middleware():
    """First, so the id covers everything - including CORS and security responses."""
    assert settings.MIDDLEWARE[0] == "apps.core.middleware.RequestIdMiddleware"


# --------------------------------------------------------------------------
# JSON logs
# --------------------------------------------------------------------------


def make_record(message="payment_verified", exc_info=None, **extra):
    record = logging.LogRecord(
        "apps.payments.services", logging.INFO, __file__, 10, message, (), exc_info
    )
    for key, value in extra.items():
        setattr(record, key, value)
    RequestIdFilter().filter(record)
    return record


def test_json_lines_are_valid_json_with_the_standard_fields():
    line = json.loads(JsonFormatter().format(make_record()))

    assert line["message"] == "payment_verified"
    assert line["level"] == "INFO"
    assert line["logger"] == "apps.payments.services"
    assert line["request_id"] == "-"
    assert line["timestamp"].endswith("+00:00")


def test_extra_fields_become_searchable_json_keys():
    line = json.loads(
        JsonFormatter().format(make_record(user_id=42, plan_slug="pro_monthly", amount_inr="499"))
    )

    assert line["user_id"] == 42
    assert line["plan_slug"] == "pro_monthly"


def test_the_current_request_id_lands_on_the_log_line():
    token = request_id_var.set("11111111-2222-3333-4444-555555555555")
    try:
        line = json.loads(JsonFormatter().format(make_record()))
    finally:
        request_id_var.reset(token)

    assert line["request_id"] == "11111111-2222-3333-4444-555555555555"


def test_secrets_passed_in_extra_are_scrubbed_from_logs():
    line = json.loads(
        JsonFormatter().format(make_record(password="hunter2", razorpay_signature="sig", user_id=1))
    )

    assert line["password"] == "[Filtered]"
    assert line["razorpay_signature"] == "[Filtered]"
    assert line["user_id"] == 1


def test_exceptions_are_included():
    try:
        raise ValueError("bad")
    except ValueError:
        record = make_record(exc_info=sys.exc_info())

    line = json.loads(JsonFormatter().format(record))

    assert "ValueError: bad" in line["exception"]


def test_unserialisable_extras_do_not_break_logging():
    line = json.loads(JsonFormatter().format(make_record(when=object())))

    assert "object" in line["when"]


def test_production_logs_json_and_development_logs_text():
    prod = build_logging(json_output=True)
    dev = build_logging(json_output=False)

    assert prod["formatters"]["default"]["()"] == "apps.core.log_format.JsonFormatter"
    assert "format" in dev["formatters"]["default"]
    assert prod["handlers"]["console"]["filters"] == ["request_id"]
    assert "apps.core.requests" not in prod["loggers"]


def test_the_logging_config_is_accepted_by_python():
    """dictConfig raises on a malformed config; validate it without replacing live logging."""
    import logging.config

    for json_output in (True, False):
        config = build_logging(json_output=json_output)
        config["disable_existing_loggers"] = False
        configurator = logging.config.DictConfigurator(config)
        formatter = configurator.configure_formatter(dict(config["formatters"]["default"]))
        assert isinstance(formatter, logging.Formatter)
