"""GET /api/v1/learning/resources/?skill=<id> - courses for one skill."""

import pytest
from rest_framework.test import APIClient

from apps.career_intel.models import LearningResource, ResourceSkill
from apps.skills.models import Skill

pytestmark = pytest.mark.django_db

URL = "/api/v1/learning/resources/"


@pytest.fixture
def client(django_user_model):
    user = django_user_model.objects.create_user(
        email="learner@example.com", password="pw-12345678", role="seeker"
    )
    c = APIClient()
    c.force_authenticate(user)
    return c


def resource(title, skills, **extra):
    r = LearningResource.objects.create(
        title=title, url=f"https://example.com/{title.replace(' ', '-')}", **extra
    )
    for s in skills:
        ResourceSkill.objects.create(resource=r, skill=s)
    return r


def titles(response):
    body = response.json()
    rows = body["results"] if isinstance(body, dict) else body
    return {r["title"] for r in rows}


def test_filters_by_skill_and_combines_with_other_filters(client):
    docker = Skill.objects.create(name="Docker")
    redis = Skill.objects.create(name="Redis")
    resource("Docker basics", [docker], is_free=True)
    resource("Docker pro", [docker], is_free=False)
    resource("Docker and Redis", [docker, redis], is_free=True)
    resource("Redis only", [redis], is_free=True)

    assert titles(client.get(URL, {"skill": docker.id})) == {
        "Docker basics",
        "Docker pro",
        "Docker and Redis",
    }
    assert titles(client.get(URL, {"skill": docker.id, "is_free": "true"})) == {
        "Docker basics",
        "Docker and Redis",
    }


def test_a_resource_with_the_skill_twice_is_listed_once(client):
    docker = Skill.objects.create(name="Docker")
    redis = Skill.objects.create(name="Redis")
    resource("Both", [docker, redis])
    body = client.get(URL, {"skill": docker.id}).json()
    assert body["count"] == 1


def test_a_bad_skill_value_is_ignored(client):
    resource("Anything", [])
    response = client.get(URL, {"skill": "abc"})
    assert response.status_code == 200
    assert titles(response) == {"Anything"}
