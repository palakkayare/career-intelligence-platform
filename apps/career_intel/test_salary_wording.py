"""
User-facing copy must not claim anonymity the system does not provide.

DATA_PROTECTION.md gap 4: salary submissions and company reviews keep an
author link for deduplication, so they are pseudonymous. Copy that says
"anonymous" overstates it.
"""

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

FORBIDDEN = ("anonymous", "anonymously", "untraceable", "we do not know who you are")


@pytest.mark.regression
def test_the_submission_reply_does_not_claim_anonymity(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)

    response = client.post(
        "/api/v1/salary/submit/",
        {
            "role_title": "Backend Developer",
            "location_city": "Bengaluru",
            "salary_inr": "1200000",
            "company_size_bucket": "medium",
            "experience_years_bucket": "5-10",
            "effective_year": 2026,
        },
        format="json",
    )

    assert response.status_code == 201
    message = response.data["message"].lower()
    for word in FORBIDDEN:
        assert word not in message, f"the reply claims {word!r}"


def test_the_reply_says_what_is_actually_protected(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)

    response = client.post(
        "/api/v1/salary/submit/",
        {
            "role_title": "Data Engineer",
            "location_city": "Pune",
            "salary_inr": "1500000",
            "company_size_bucket": "medium",
            "experience_years_bucket": "5-10",
            "effective_year": 2026,
        },
        format="json",
    )

    message = response.data["message"].lower()
    assert "name is never shown" in message
    assert "aggregate" in message
    assert "private record" in message
