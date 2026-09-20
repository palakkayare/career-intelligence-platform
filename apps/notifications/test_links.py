"""
Every link the backend sends must be a route the web app renders.

Regression: triggers wrote API-style paths ("/resumes/<id>/",
"/applications/me/<id>", "/jobs/matches/"). The in-app bell translated a
few of them; emails used them as-is, so "View Full Report" and friends
landed on the login screen.
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.notifications import links

# Mirror of the React router (src/App.jsx). Update both together.
FRONTEND_ROUTES = [
    "/me/applications",
    "/me/applications/:id",
    "/recruiter/jobs/:id/applications",
    "/recruiter/jobs/:id/edit",
    "/jobs/:id",
    "/billing/invoices/:id",
    "/subscription",
    "/pricing",
    "/account/resumes/:id/parsed",
    "/recommendations",
    "/referrals",
    "/me/who-viewed",
    "/candidates",
]


def _matches_a_route(path):
    for route in FRONTEND_ROUTES:
        pattern = "^" + re.sub(r":[^/]+", "[^/]+", route) + "$"
        if re.match(pattern, path):
            return True
    return False


@pytest.mark.parametrize(
    "path",
    [
        links.seeker_application(7),
        links.seeker_applications(),
        links.recruiter_job_applications("abc"),
        links.recruiter_job_edit("abc"),
        links.job("abc"),
        links.invoice(52),
        links.subscription(),
        links.pricing(),
        links.resume_analysis("abc"),
        links.job_matches(),
        links.referrals(),
        links.who_viewed_me(),
        links.candidate_search(),
    ],
)
def test_every_link_is_a_real_route(path):
    assert _matches_a_route(path), path


def test_job_matches_is_not_mistaken_for_a_job_id():
    # "/jobs/matches" would open the job-detail page for a job called "matches".
    assert not links.job_matches().startswith("/jobs/")


def test_no_trigger_writes_a_path_by_hand():
    """New notifications must go through links.py."""
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for py in root.rglob("*.py"):
        if "test" in py.name or "migrations" in py.parts:
            continue
        for n, line in enumerate(py.read_text().splitlines(), 1):
            if re.search(r"""\blink=f?["']/""", line):
                offenders.append(f"{py.relative_to(root)}:{n}: {line.strip()}")
    assert offenders == []


def test_resume_notification_points_at_the_analysis_page():
    from apps.notifications import triggers

    resume = SimpleNamespace(
        user=object(),
        name="CV",
        public_id="r-1",
        ats_score=94,
        resume_skills=SimpleNamespace(count=lambda: 12),
    )
    with patch.object(triggers.NotificationService, "create") as create:
        triggers.notify_resume_analysis_complete(resume)
    assert create.call_args.kwargs["link"] == "/account/resumes/r-1/parsed"


@pytest.mark.django_db
def test_emails_greet_by_profile_name_not_email(django_user_model):
    from apps.notifications.tasks import _greeting_name

    user = django_user_model.objects.create_user(
        email="seeker1@test.com", password="pw-12345678", role="seeker"
    )
    assert _greeting_name(user) == "there"

    user.seeker_profile.full_name = "Priya Sharma"
    user.seeker_profile.save()
    user.refresh_from_db()
    assert _greeting_name(user) == "Priya"

    user.full_name = "Priya S."
    assert _greeting_name(user) == "Priya"


# ── join request emails ────────────────────────────────────────────────


def test_join_request_emails_have_their_templates():
    """
    Both kinds are sent instantly, and an instant kind without templates
    means the notification appears in-app while the email quietly never goes.
    """
    from django.template.loader import get_template

    from apps.notifications.tasks import KIND_TEMPLATES

    for kind in ("company_join_request", "company_join_decided"):
        directory = KIND_TEMPLATES.get(kind)
        assert directory, f"{kind} has no template directory"
        for name in ("subject.txt", "body.txt", "body.html"):
            get_template(f"emails/{directory}/{name}")


def test_the_decision_email_reads_differently_when_declined():
    from django.template.loader import render_to_string

    approved = render_to_string(
        "emails/company_join_decided/body.txt",
        {"user_name": "Vikram", "company_name": "Acme", "approved": True, "link": "/x"},
    )
    declined = render_to_string(
        "emails/company_join_decided/body.txt",
        {"user_name": "Vikram", "company_name": "Acme", "approved": False, "link": "/x"},
    )

    assert "was approved" in approved
    assert "not approved" in declined
    # A declined person should not be pointed at a team they are not part of.
    assert "your own" in declined
