"""
Target roles are only as useful as the skills attached to them.

The skill gap measures a person against a role's required skills. A role with
no skills attached does not fail loudly - it reports "nothing to learn",
which reads like good news and is the opposite of the truth.
"""

import pytest
from django.core.management import call_command

from apps.career_intel.management.commands.seed_target_roles import ROLE_DATA
from apps.career_intel.models import TargetRole, TargetRoleSkill
from apps.skills.models import Skill

pytestmark = pytest.mark.django_db


def seed_everything():
    call_command("seed_skills")
    call_command("seed_target_roles")


def test_every_role_gets_its_skills(capsys):
    seed_everything()

    for role in TargetRole.objects.all():
        assert TargetRoleSkill.objects.filter(
            target_role=role
        ).exists(), f"{role.name} has no skills, so its skill gap would always read as complete"


def test_no_skill_link_is_dropped():
    """
    Regression: the lists are written by hand, so they say "Google Cloud"
    where the taxonomy stores "Google Cloud Platform". Those links used to be
    skipped with a warning nobody reads.
    """
    seed_everything()

    expected = sum(len(role.get("skills", [])) for role in ROLE_DATA)
    assert TargetRoleSkill.objects.count() == expected


def test_a_skill_is_found_by_its_alias():
    call_command("seed_skills")
    gcp = Skill.objects.get(name="Google Cloud Platform")
    assert "google cloud" in [a.lower() for a in gcp.aliases]

    call_command("seed_target_roles")

    devops = TargetRole.objects.get(slug="devops-engineer")
    linked = {s.skill.name for s in TargetRoleSkill.objects.filter(target_role=devops)}
    assert "Google Cloud Platform" in linked


def test_running_it_twice_adds_nothing():
    seed_everything()
    roles, links = TargetRole.objects.count(), TargetRoleSkill.objects.count()

    call_command("seed_target_roles")

    assert (TargetRole.objects.count(), TargetRoleSkill.objects.count()) == (roles, links)


def test_every_role_has_at_least_one_critical_skill():
    """A role made only of "nice to have" cannot tell anyone what to learn first."""
    seed_everything()

    for role in TargetRole.objects.all():
        assert TargetRoleSkill.objects.filter(
            target_role=role, importance="critical"
        ).exists(), f"{role.name} has no critical skill"
