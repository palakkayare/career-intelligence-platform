"""
Every instant notification has an email template that exists and renders.

Regression: resume_analysis_complete, application_withdrawn and
subscription_expired had none. The worker raised TemplateDoesNotExist,
retried three times and the email never went out. Nothing failed in tests,
because nothing rendered them.
"""

import pytest
from django.core import mail
from django.template.loader import get_template
from django.test import override_settings

from apps.notifications.models import DeliveryPriority, Notification, NotificationKind
from apps.notifications.service import KIND_PRIORITIES
from apps.notifications.tasks import KIND_TEMPLATES, send_notification_email

pytestmark = pytest.mark.django_db

INSTANT_KINDS = [
    kind for kind, priority in KIND_PRIORITIES.items() if priority == DeliveryPriority.INSTANT
]


@pytest.mark.regression
@pytest.mark.parametrize("kind", INSTANT_KINDS)
def test_every_instant_email_has_all_three_templates(kind):
    template_dir = KIND_TEMPLATES.get(kind)
    assert template_dir, f"{kind} is sent instantly but has no template directory"

    for name in ("subject.txt", "body.txt", "body.html"):
        get_template(f"emails/{template_dir}/{name}")


@pytest.mark.regression
@override_settings(FRONTEND_URL="https://app.example.com")
@pytest.mark.parametrize(
    "kind, context, expected",
    [
        (
            NotificationKind.RESUME_ANALYSIS_COMPLETE,
            {"resume_name": "My CV", "ats_score": 82, "skills_found": 9},
            "ATS score: 82/100",
        ),
        (
            NotificationKind.APPLICATION_WITHDRAWN,
            {"seeker_name": "Priya", "job_title": "Backend Developer"},
            "Backend Developer",
        ),
        (
            NotificationKind.SUBSCRIPTION_EXPIRED,
            {"plan_name": "Pro Monthly", "expired_on": "01 Oct 2026"},
            "01 Oct 2026",
        ),
    ],
)
def test_the_missing_emails_now_send_with_one_absolute_link(seeker_user, kind, context, expected):
    notif = Notification.objects.create(
        user=seeker_user,
        kind=kind,
        title="t",
        message="m",
        link="/somewhere/",
        context=context,
        delivery_priority=DeliveryPriority.INSTANT,
    )

    send_notification_email.delay(notif.id)

    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    html = email.alternatives[0][0]
    assert expected in email.body
    assert "https://app.example.com/somewhere/" in email.body
    assert "https://app.example.com/somewhere/" in html
    # The context link is already absolute; prefixing it again doubled it.
    assert "https://app.example.comhttps" not in email.body + html

    notif.refresh_from_db()
    assert notif.is_emailed
