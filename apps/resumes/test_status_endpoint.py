"""
GET /api/v1/resumes/<id>/status/

The upload screen polls while parsing runs. It used to poll the detail
endpoint, which carries the extracted text and the parsed payload - tens of
kilobytes pulled down every few seconds to read one status field.
"""

import pytest
from rest_framework.test import APIClient

from apps.resumes.models import Resume

pytestmark = pytest.mark.django_db


@pytest.fixture
def resume(django_user_model):
    user = django_user_model.objects.create_user(
        email="polling@seeker.test", password="pw-12345678", role="seeker", is_email_verified=True
    )
    return Resume.objects.create(
        user=user,
        name="CV",
        original_filename="cv.pdf",
        file_size_bytes=120_000,
        status=Resume.Status.PARSING,
        extracted_text="x" * 50_000,
        parsed_data={"sections": {"experience": "y" * 10_000}},
    )


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def url(resume, suffix=""):
    return f"/api/v1/resumes/{resume.public_id}/{suffix}"


def test_status_answers_without_the_whole_resume(resume):
    response = client_for(resume.user).get(url(resume, "status/"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == Resume.Status.PARSING
    assert "analysis_state" in body
    # The point of the endpoint:
    assert "extracted_text" not in body
    assert "parsed_data" not in body


def test_it_is_far_smaller_than_the_detail_response(resume):
    client = client_for(resume.user)

    status_size = len(client.get(url(resume, "status/")).content)
    detail_size = len(client.get(url(resume)).content)

    assert status_size * 20 < detail_size


def test_another_user_cannot_watch_your_resume(django_user_model, resume):
    stranger = django_user_model.objects.create_user(
        email="stranger@seeker.test", password="pw-12345678", role="seeker", is_email_verified=True
    )
    assert client_for(stranger).get(url(resume, "status/")).status_code == 404


def test_a_finished_resume_reports_its_score(resume):
    Resume.objects.filter(pk=resume.pk).update(status=Resume.Status.PARSED, ats_score=74)

    body = client_for(resume.user).get(url(resume, "status/")).json()

    assert body["status"] == Resume.Status.PARSED
    assert body["ats_score"] == 74
