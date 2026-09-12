"""
The OpenAPI schema builds, and documentation coverage only improves.

Schema generation walks every view and serializer in the project, so it fails
loudly on the kind of mistake that otherwise only shows up as a 500 for a
user - which is how the broken seeker profile serializer was found.
"""

import pytest
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

METHODS = ("get", "post", "put", "patch", "delete")

# Operations whose response body the generator cannot infer, because the view
# builds its response by hand. Ratchet: annotate views with @extend_schema and
# lower this number. It must never go up.
MAX_UNDOCUMENTED_RESPONSES = 130


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def operations(schema):
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation


def test_the_schema_covers_the_whole_api(schema):
    assert len(schema["paths"]) > 150


def test_authentication_is_documented_as_bearer_jwt(schema):
    """Without the extension, Swagger UI has no Authorize button."""
    assert schema["components"]["securitySchemes"]["jwtAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }


def test_core_endpoints_document_their_response_body(schema):
    for path, method in [
        ("/api/v1/plans/", "get"),
        ("/api/v1/seekers/me/", "get"),
        ("/api/v1/jobs/", "get"),
    ]:
        operation = schema["paths"][path][method]
        assert operation["responses"]["200"]["content"], f"{method.upper()} {path}"


def test_undocumented_responses_do_not_increase(schema):
    undocumented = [
        f"{method.upper()} {path}"
        for path, method, operation in operations(schema)
        if not any(
            response.get("content")
            for status, response in operation["responses"].items()
            if status.startswith("2")
        )
    ]

    assert len(undocumented) <= MAX_UNDOCUMENTED_RESPONSES, (
        f"{len(undocumented)} operations have no documented response body, up from "
        f"{MAX_UNDOCUMENTED_RESPONSES}. Annotate the new view with @extend_schema."
    )


def test_the_schema_endpoint_serves_yaml(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)

    response = client.get(reverse("schema"))

    assert response.status_code == 200
    assert b"openapi" in response.content


def test_the_docs_page_loads():
    response = APIClient().get(reverse("docs"))

    assert response.status_code == 200
