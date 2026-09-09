"""
Profile strength scoring.

The score is out of 100 across six sections. It is the number every seeker
sees on their dashboard and the thing that nudges them into completing a
profile, so the weights are a product decision worth pinning down.
"""
from datetime import date

import pytest

from apps.seekers.models import Education, SeekerSkill, WorkExperience
from apps.seekers.services import ProfileStrengthService

pytestmark = pytest.mark.django_db

SECTION_MAXIMUMS = {
    'basic_info': 20,
    'career_goals': 15,
    'skills': 25,
    'experience': 20,
    'education': 10,
    'portfolio': 10,
}


def score(profile):
    return ProfileStrengthService.calculate(profile)


@pytest.fixture
def make_skill(db):
    from apps.skills.models import Skill

    def _make(name):
        return Skill.objects.create(name=name)
    return _make


def add_skills(profile, count, make_skill):
    """
    Names are keyed off the existing count so a second call does not try to
    recreate 'Skill 0' - Skill.name is unique.
    """
    offset = SeekerSkill.objects.filter(seeker=profile).count()
    for index in range(offset, offset + count):
        SeekerSkill.objects.create(
            seeker=profile, skill=make_skill(f'Skill {index}'),
        )


def add_experience(profile, count=1):
    for index in range(count):
        WorkExperience.objects.create(
            seeker=profile,
            company_name=f'Company {index}',
            job_title='Backend Developer',
            start_date=date(2020 + index, 1, 1),
        )


def add_education(profile, institution='NITW'):
    return Education.objects.create(
        seeker=profile,
        institution_name=institution,
        degree='B.Tech',
        start_year=2018,
        end_year=2022,
    )


def fill_everything_except_photo(profile, make_skill):
    profile.full_name = 'Palak K'
    profile.bio = 'Backend engineer focused on payments and search systems. ' * 2
    profile.location = 'Bangalore'
    profile.current_title = 'Backend Developer'
    profile.target_role = 'Senior Backend Engineer'
    profile.github_url = 'https://github.com/example'
    profile.linkedin_url = 'https://linkedin.com/in/example'
    profile.save()

    add_skills(profile, 5, make_skill)
    add_experience(profile, 2)
    add_education(profile)


# --------------------------------------------------------------------------
# Totals
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_the_sections_add_up_to_100():
    """
    Regression: seekers/services.py sat at 0% coverage. If the section
    maximums stopped summing to 100 the score would silently become
    unreachable, and nobody would ever see "Profile complete".
    """
    assert sum(SECTION_MAXIMUMS.values()) == 100


def test_a_bare_profile_scores_low(seeker):
    """The signal-created profile has an email and nothing else."""
    result = score(seeker)

    assert result['score'] < 20
    assert set(result['breakdown']) == set(SECTION_MAXIMUMS)


def test_a_profile_without_a_photo_scores_95(seeker, make_skill):
    fill_everything_except_photo(seeker, make_skill)

    result = score(seeker)

    assert result['score'] == 95
    assert result['breakdown']['skills'] == 25
    assert result['breakdown']['experience'] == 20
    assert result['breakdown']['education'] == 10
    assert result['breakdown']['portfolio'] == 10


def test_no_section_can_exceed_its_maximum(seeker, make_skill):
    add_skills(seeker, 20, make_skill)
    add_experience(seeker, 10)
    seeker.github_url = 'https://github.com/example'
    seeker.linkedin_url = 'https://linkedin.com/in/example'
    seeker.behance_url = 'https://behance.net/example'
    seeker.portfolio_url = 'https://example.com'
    seeker.save()

    breakdown = score(seeker)['breakdown']

    for section, maximum in SECTION_MAXIMUMS.items():
        assert breakdown[section] <= maximum, f'{section} exceeded {maximum}'


# --------------------------------------------------------------------------
# Individual sections
# --------------------------------------------------------------------------

def test_a_short_bio_earns_nothing(seeker):
    seeker.bio = 'Hi.'
    seeker.save()
    short = score(seeker)['breakdown']['basic_info']

    seeker.bio = 'Backend engineer focused on payments and search systems.'
    seeker.save()
    proper = score(seeker)['breakdown']['basic_info']

    assert proper > short


def test_target_role_is_worth_more_than_current_title(seeker):
    """Target role drives matching, so it carries double the weight."""
    seeker.current_title = 'Backend Developer'
    seeker.save()
    with_title = score(seeker)['breakdown']['career_goals']

    seeker.current_title = ''
    seeker.target_role = 'Senior Backend Engineer'
    seeker.save()
    with_target = score(seeker)['breakdown']['career_goals']

    assert with_target > with_title


def test_skills_are_worth_five_points_each(seeker, make_skill):
    add_skills(seeker, 3, make_skill)

    assert score(seeker)['breakdown']['skills'] == 15


def test_the_sixth_skill_adds_nothing(seeker, make_skill):
    add_skills(seeker, 5, make_skill)
    at_five = score(seeker)['breakdown']['skills']

    add_skills(seeker, 3, make_skill)

    assert score(seeker)['breakdown']['skills'] == at_five == 25


def test_education_is_all_or_nothing(seeker):
    assert score(seeker)['breakdown']['education'] == 0

    add_education(seeker)

    assert score(seeker)['breakdown']['education'] == 10


def test_two_portfolio_links_max_out_the_section(seeker):
    seeker.github_url = 'https://github.com/example'
    seeker.save()
    one_link = score(seeker)['breakdown']['portfolio']

    seeker.linkedin_url = 'https://linkedin.com/in/example'
    seeker.behance_url = 'https://behance.net/example'
    seeker.save()

    assert one_link == 5
    assert score(seeker)['breakdown']['portfolio'] == 10


# --------------------------------------------------------------------------
# Next-step suggestion
# --------------------------------------------------------------------------

def test_the_suggestion_targets_the_biggest_gap(seeker):
    """Skills is worth 25, the most of any section, so it goes first."""
    result = score(seeker)

    assert 'skills' in result['next_step'].lower()


def test_the_suggestion_moves_on_once_a_section_is_filled(seeker, make_skill):
    add_skills(seeker, 5, make_skill)

    result = score(seeker)

    assert 'skills' not in result['next_step'].lower()


def test_a_finished_profile_is_congratulated(seeker, make_skill):
    """
    Reachable only with a photo, which needs a real file - so the field is
    set directly rather than uploading one just to see this string.
    """
    fill_everything_except_photo(seeker, make_skill)
    seeker.profile_photo = 'seekers/photo.jpg'
    seeker.save()

    result = score(seeker)

    assert result['score'] == 100
    assert 'complete' in result['next_step'].lower()