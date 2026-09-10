"""
Skill taxonomy: resolving names and merging duplicates.

The problem being solved: "React" and "ReactJS" as two rows means a seeker
who lists one scores zero against a job asking for the other. Fixing that at
score time would hide the symptom; these fix the taxonomy.
"""

import pytest
from rest_framework.exceptions import ValidationError

from apps.skills.models import Skill
from apps.skills.services import SkillMergeService, SkillResolver

pytestmark = pytest.mark.django_db


def make_skill(name, aliases=None, deprecated=False):
    return Skill.objects.create(
        name=name,
        aliases=aliases or [],
        is_deprecated=deprecated,
    )


# --------------------------------------------------------------------------
# Resolving
# --------------------------------------------------------------------------


def test_an_exact_name_resolves():
    skill = make_skill("Python")

    assert SkillResolver.resolve("Python") == skill


def test_resolution_ignores_case_and_spacing():
    skill = make_skill("Python")

    assert SkillResolver.resolve("python") == skill
    assert SkillResolver.resolve("  Python  ") == skill


@pytest.mark.regression
def test_an_alias_resolves_to_the_canonical_skill():
    """
    The whole point. Without this, a seeker listing ReactJS scores zero
    against a job asking for React.
    """
    react = make_skill("React", aliases=["ReactJS", "React.js"])

    assert SkillResolver.resolve("ReactJS") == react
    assert SkillResolver.resolve("react.js") == react


def test_an_unknown_name_resolves_to_nothing():
    make_skill("Python")

    assert SkillResolver.resolve("Cobol") is None


def test_an_empty_name_resolves_to_nothing():
    assert SkillResolver.resolve("") is None
    assert SkillResolver.resolve(None) is None
    assert SkillResolver.resolve("   ") is None


def test_a_deprecated_skill_is_not_resolved():
    make_skill("Flash", deprecated=True)

    assert SkillResolver.resolve("Flash") is None


@pytest.mark.regression
def test_an_exact_name_beats_someone_elses_alias():
    """
    If "Go" is a real skill and also an alias of "Golang", typing Go must
    return Go.
    """
    go = make_skill("Go")
    make_skill("Golang", aliases=["Go"])

    assert SkillResolver.resolve("Go") == go


def test_an_alias_that_only_partially_matches_is_not_used():
    """
    Alias lookup narrows with icontains and then checks properly - a
    substring hit must not count as a match.
    """
    make_skill("JavaScript", aliases=["JS"])

    assert SkillResolver.resolve("J") is None


# --------------------------------------------------------------------------
# Resolve or create
# --------------------------------------------------------------------------


def test_an_existing_skill_is_reused():
    python = make_skill("Python")

    skill, created = SkillResolver.resolve_or_create("python")

    assert skill == python
    assert created is False


def test_an_alias_does_not_create_a_duplicate():
    react = make_skill("React", aliases=["ReactJS"])

    skill, created = SkillResolver.resolve_or_create("ReactJS")

    assert skill == react
    assert created is False
    assert Skill.objects.count() == 1


@pytest.mark.regression
def test_a_new_skill_arrives_unapproved():
    """
    Anyone typing into a skill box can create one. An unmoderated taxonomy
    fills with typos within a week, so new entries wait for a human - but
    they still work for matching in the meantime.
    """
    skill, created = SkillResolver.resolve_or_create("Elixir")

    assert created is True
    assert skill.is_approved is False
    assert skill.is_deprecated is False


def test_creating_with_an_empty_name_is_refused():
    with pytest.raises(ValidationError):
        SkillResolver.resolve_or_create("")


def test_resolving_many_separates_the_misses():
    make_skill("Python")
    make_skill("Django")

    matched, unmatched = SkillResolver.resolve_many(
        ["Python", "Django", "Responsibilities", "References"],
    )

    assert {s.name for s in matched} == {"Python", "Django"}
    assert unmatched == ["Responsibilities", "References"]


@pytest.mark.regression
def test_resolving_many_creates_nothing():
    """
    Used by the resume parser, where most extracted strings are not skills.
    "Responsibilities" must not become one.
    """
    make_skill("Python")

    SkillResolver.resolve_many(["Python", "Responsibilities"])

    assert Skill.objects.count() == 1


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_merging_deprecates_the_source():
    """
    Regression: Feature 10 asks for add, merge and deprecate. Add and
    deprecate existed; merge did not, so duplicates accumulated with no way
    to clean them up.
    """
    source = make_skill("ReactJS")
    target = make_skill("React")

    SkillMergeService.merge(source, target)

    source.refresh_from_db()
    assert source.is_deprecated is True


def test_the_source_is_not_deleted():
    """Deleting it would break anything historical that points at it."""
    source = make_skill("ReactJS")
    target = make_skill("React")

    SkillMergeService.merge(source, target)

    assert Skill.objects.filter(pk=source.pk).exists()


@pytest.mark.regression
def test_the_merged_name_still_resolves():
    """
    Someone typing ReactJS after the merge should land on React, not on
    nothing.
    """
    source = make_skill("ReactJS")
    target = make_skill("React")

    SkillMergeService.merge(source, target)

    assert SkillResolver.resolve("ReactJS") == target


def test_the_target_absorbs_the_sources_aliases():
    source = make_skill("ReactJS", aliases=["React.js"])
    target = make_skill("React")

    SkillMergeService.merge(source, target)

    target.refresh_from_db()
    assert "ReactJS" in target.aliases
    assert "React.js" in target.aliases


def test_absorbing_aliases_does_not_duplicate_them():
    source = make_skill("ReactJS", aliases=["React.js"])
    target = make_skill("React", aliases=["react.js"])

    SkillMergeService.merge(source, target)

    target.refresh_from_db()
    lowered = [str(a).lower() for a in target.aliases]
    assert lowered.count("react.js") == 1


def test_merging_a_skill_into_itself_is_refused():
    skill = make_skill("React")

    with pytest.raises(ValidationError):
        SkillMergeService.merge(skill, skill)


def test_seeker_skills_move_to_the_target(seeker):
    from apps.seekers.models import SeekerSkill

    source = make_skill("ReactJS")
    target = make_skill("React")
    SeekerSkill.objects.create(seeker=seeker, skill=source)

    SkillMergeService.merge(source, target)

    assert SeekerSkill.objects.filter(seeker=seeker, skill=target).exists()
    assert not SeekerSkill.objects.filter(seeker=seeker, skill=source).exists()


@pytest.mark.regression
def test_a_seeker_holding_both_ends_up_with_one(seeker):
    """
    Someone who listed React and ReactJS separately must not hit a unique
    constraint error mid-merge.
    """
    from apps.seekers.models import SeekerSkill

    source = make_skill("ReactJS")
    target = make_skill("React")
    SeekerSkill.objects.create(seeker=seeker, skill=source)
    SeekerSkill.objects.create(seeker=seeker, skill=target)

    SkillMergeService.merge(source, target)

    assert SeekerSkill.objects.filter(seeker=seeker).count() == 1


def test_job_requirements_move_to_the_target(make_job):
    source = make_skill("ReactJS")
    target = make_skill("React")
    job = make_job()
    job.required_skills.set([source])

    SkillMergeService.merge(source, target)

    assert target in job.required_skills.all()
    assert source not in job.required_skills.all()


def test_a_job_asking_for_both_ends_up_asking_for_one(make_job):
    source = make_skill("ReactJS")
    target = make_skill("React")
    job = make_job()
    job.required_skills.set([source, target])

    SkillMergeService.merge(source, target)

    assert list(job.required_skills.all()) == [target]


def test_the_merge_reports_what_moved(seeker, make_job):
    from apps.seekers.models import SeekerSkill

    source = make_skill("ReactJS")
    target = make_skill("React")
    SeekerSkill.objects.create(seeker=seeker, skill=source)

    result = SkillMergeService.merge(source, target)

    assert result["source"] == "ReactJS"
    assert result["target"] == "React"
    assert result["moved"]["seeker_skills"]["moved"] == 1


# --------------------------------------------------------------------------
# Finding duplicates
# --------------------------------------------------------------------------


def test_names_differing_only_by_spacing_are_flagged():
    make_skill("Node JS")
    make_skill("NodeJS")

    groups = SkillMergeService.find_likely_duplicates()

    assert len(groups) == 1
    assert {s.name for s in groups[0]["skills"]} == {"Node JS", "NodeJS"}


def test_genuinely_different_skills_are_not_flagged():
    make_skill("Python")
    make_skill("Django")

    assert SkillMergeService.find_likely_duplicates() == []


@pytest.mark.regression
def test_the_finder_only_suggests():
    """
    Normalisation cannot tell a duplicate from a distinct name. "Go" and
    "Golang" are the same thing and are not flagged; something has to stay
    a human decision, which is why nothing merges automatically.
    """
    make_skill("Go")
    make_skill("Golang")

    assert SkillMergeService.find_likely_duplicates() == []
    assert Skill.objects.filter(is_deprecated=False).count() == 2


def test_deprecated_skills_are_left_out_of_the_search():
    make_skill("Node JS")
    make_skill("NodeJS", deprecated=True)

    assert SkillMergeService.find_likely_duplicates() == []


# --------------------------------------------------------------------------
# The management command
# --------------------------------------------------------------------------


def test_the_command_lists_without_merging(capsys):
    from django.core.management import call_command

    make_skill("Node JS")
    make_skill("NodeJS")

    call_command("merge_duplicate_skills")

    assert Skill.objects.filter(is_deprecated=True).count() == 0


def test_the_command_merges_with_apply():
    from django.core.management import call_command

    make_skill("Node JS")
    make_skill("NodeJS")

    call_command("merge_duplicate_skills", "--apply", verbosity=0)

    assert Skill.objects.filter(is_deprecated=True).count() == 1


def test_the_command_can_merge_one_named_pair():
    from django.core.management import call_command

    source = make_skill("ReactJS")
    make_skill("React")

    call_command(
        "merge_duplicate_skills",
        source="ReactJS",
        target="React",
        verbosity=0,
    )

    source.refresh_from_db()
    assert source.is_deprecated is True


def test_the_command_refuses_an_unknown_skill():
    from django.core.management import call_command
    from django.core.management.base import CommandError

    make_skill("React")

    with pytest.raises(CommandError):
        call_command(
            "merge_duplicate_skills",
            source="Nonsense",
            target="React",
            verbosity=0,
        )


# --------------------------------------------------------------------------
# Slug collisions
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_names_that_differ_only_by_symbols_can_coexist():
    """
    Regression: slug is unique and slugify() strips symbols, so slugify("C")
    and slugify("C#") both produced "c" - meaning C# could not be added to a
    taxonomy that already had C. The same applied to C++, F# and .NET.
    """
    make_skill("C")
    csharp = make_skill("C#")

    assert csharp.pk
    assert Skill.objects.filter(is_deprecated=False).count() == 2


@pytest.mark.parametrize(
    "first,second",
    [
        ("C", "C++"),
        ("F", "F#"),
        ("NET", ".NET"),
    ],
)
def test_symbol_variants_get_distinct_slugs(first, second):
    a = make_skill(first)
    b = make_skill(second)

    assert a.slug != b.slug
