"""
The seeder can be run on a live database without fear.

Match scores, the skill gap and learning recommendations all read this table,
so it has to be safe to top up - including after people have added skills of
their own.
"""

import pytest
from django.core.management import call_command

from apps.skills.data.skill_catalogue import SKILLS, SLUG_OVERRIDES
from apps.skills.models import Skill

pytestmark = pytest.mark.django_db


def seed(**kwargs):
    call_command("seed_skills", **kwargs)


def test_it_seeds_the_whole_catalogue():
    seed()
    assert Skill.objects.count() == len(SKILLS)
    assert Skill.objects.filter(name="Django").exists()
    assert Skill.objects.filter(name="Kubernetes").exists()


def test_running_it_twice_changes_nothing():
    seed()
    first = Skill.objects.count()

    seed()

    assert Skill.objects.count() == first


def test_a_skill_someone_added_keeps_its_aliases():
    """Their alias is theirs; ours are added alongside, not over."""
    Skill.objects.create(name="Python", category="other", aliases=["python3.11"])

    seed()

    python = Skill.objects.get(name="Python")
    assert "python3.11" in python.aliases  # kept
    assert "py" in python.aliases  # and ours added
    assert python.category == "programming"  # corrected


def test_skills_outside_the_catalogue_are_left_alone():
    Skill.objects.create(name="COBOL on Mainframe", category="other", aliases=[])

    seed()

    assert Skill.objects.filter(name="COBOL on Mainframe").exists()


def test_dry_run_writes_nothing():
    seed(dry_run=True)
    assert Skill.objects.count() == 0


def test_every_catalogue_name_is_unique():
    names = [name.lower() for name, _, _ in SKILLS]
    duplicates = {n for n in names if names.count(n) > 1}
    assert duplicates == set()


def test_awkward_names_get_usable_slugs():
    seed()

    for name, expected in SLUG_OVERRIDES.items():
        if Skill.objects.filter(name=name).exists():
            assert Skill.objects.get(name=name).slug == expected


def test_aliases_do_not_collide_across_skills():
    """
    Resume parsing matches on aliases, so the same alias on two skills would
    make extraction ambiguous.
    """
    seen = {}
    for name, _, aliases in SKILLS:
        for alias in aliases:
            key = alias.lower()
            assert key not in seen, f"{alias!r} is on both {seen.get(key)} and {name}"
            seen[key] = name
