"""
The seeds agree with each other.

Regression: eight skills used by the target-role, learning-resource and
career-path seeds were never created by seed_skills. The commands printed a
warning and skipped the link, so a fresh database silently had roles and
career paths with missing skill requirements.
"""

from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db

DEPENDENT_SEEDS = ["seed_target_roles", "seed_learning_resources", "seed_career_paths"]


def run(command):
    out, err = StringIO(), StringIO()
    call_command(command, stdout=out, stderr=err)
    return (out.getvalue() + err.getvalue()).lower()


@pytest.mark.regression
def test_every_skill_the_seeds_need_is_seeded():
    run("seed_skills")

    for command in DEPENDENT_SEEDS:
        output = run(command)
        assert "not found" not in output, f"{command} references a missing skill:\n{output}"
        assert "skipped" not in output, f"{command} skipped links:\n{output}"


def test_seeding_twice_creates_nothing_new():
    """Production re-runs these after every change to the seed data."""
    from apps.skills.models import Skill

    run("seed_skills")
    count = Skill.objects.count()
    run("seed_skills")

    assert Skill.objects.count() == count
