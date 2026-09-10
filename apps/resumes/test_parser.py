"""
Resume parsing.

Everything tested here is deterministic: section detection, contact
extraction, confidence scoring and ATS points are all plain string and
arithmetic work. The one spaCy-dependent step (_extract_skills) is left
out - it needs a language model and its behaviour is statistical, which
makes for slow and flaky tests.

This is a paid feature and the ATS number is the headline output, so the
point breakdown is worth pinning down.
"""

import pytest

from apps.resumes.models import ResumeSkill
from apps.resumes.parser import ResumeParserService as Parser

detect = Parser._detect_sections
contact_of = Parser._extract_contact
confidence_of = Parser._compute_confidence
ats_of = Parser._calculate_ats_score


RESUME = """Palak Kayare
palak@example.com | +91 98765 43210
linkedin.com/in/palakkayare | github.com/palakkayare

EXPERIENCE
Backend Developer at Test Corp, 2022 to present.
Built the payments service and the resume parser.

EDUCATION
B.Tech in Computer Science, NITW, 2022.

SKILLS
Python, Django, PostgreSQL, Redis, Celery
"""


# --------------------------------------------------------------------------
# Section detection
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_the_three_standard_sections_are_found():
    """Regression: parser.py was the last module at 0% coverage."""
    sections = detect(RESUME)

    assert set(sections) == {"experience", "education", "skills"}


def test_section_content_stops_at_the_next_header():
    sections = detect(RESUME)

    assert "Test Corp" in sections["experience"]
    assert "NITW" not in sections["experience"]


def test_the_last_section_runs_to_the_end():
    sections = detect(RESUME)

    assert "Celery" in sections["skills"]


@pytest.mark.parametrize(
    "header",
    [
        "EXPERIENCE",
        "Work Experience",
        "PROFESSIONAL EXPERIENCE",
        "Employment",
    ],
)
def test_experience_header_variants(header):
    sections = detect(f"{header}\nBackend Developer at Test Corp")

    assert "experience" in sections


@pytest.mark.parametrize(
    "header",
    [
        "SKILLS",
        "Technical Skills",
        "Technologies",
        "Expertise",
    ],
)
def test_skills_header_variants(header):
    sections = detect(f"{header}\nPython, Django")

    assert "skills" in sections


@pytest.mark.regression
def test_a_header_word_mid_sentence_is_not_a_header():
    """
    'I have experience with Django' must not open an experience section, or
    the whole rest of the resume lands in the wrong bucket.
    """
    sections = detect("I have experience with Django and education in CS.")

    assert sections == {}


def test_a_resume_with_no_headers_yields_nothing():
    assert detect("Just a wall of text with no structure at all.") == {}


def test_empty_text_is_handled():
    assert detect("") == {}


# --------------------------------------------------------------------------
# Contact extraction
# --------------------------------------------------------------------------


def test_every_contact_field_is_found():
    contact = contact_of(RESUME)

    assert contact["email"] == "palak@example.com"
    assert contact["phone"]
    assert contact["linkedin"] == "https://linkedin.com/in/palakkayare"
    assert contact["github"] == "https://github.com/palakkayare"


def test_missing_contact_details_come_back_as_none():
    contact = contact_of("Just a name and nothing else.")

    assert contact == {
        "email": None,
        "phone": None,
        "linkedin": None,
        "github": None,
    }


@pytest.mark.regression
def test_a_year_is_not_mistaken_for_a_phone_number():
    """
    The phone pattern is loose enough to match '2020-2024'. The digit-count
    check is what stops a date landing in the phone field.
    """
    contact = contact_of("Worked there 2020 - 2024.")

    assert contact["phone"] is None


def test_a_real_phone_number_survives_the_digit_check():
    assert contact_of("Call +91 98765 43210")["phone"]


@pytest.mark.regression
def test_contact_details_are_only_read_from_the_top():
    """
    A colleague's address in a reference block at the bottom must not become
    the candidate's own email.
    """
    text = "Palak\n" + ("filler line\n" * 400) + "referee@somewhere.com"

    assert contact_of(text)["email"] is None


def test_profile_urls_are_found_anywhere_in_the_document():
    """Unlike email, these are unambiguous wherever they appear."""
    text = "Palak\n" + ("filler\n" * 400) + "github.com/palakkayare"

    assert contact_of(text)["github"] == "https://github.com/palakkayare"


def test_profile_url_matching_ignores_case():
    contact = contact_of("LinkedIn.com/in/Someone")

    assert contact["linkedin"] is not None


# --------------------------------------------------------------------------
# Skill confidence
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_the_skills_section_is_the_most_trusted_source():
    """
    A skill listed under SKILLS is a claim; the same word in a job title is
    probably incidental. The scores have to reflect that ordering.
    """
    skills_conf, _ = confidence_of(1, {"skills"})
    experience_conf, _ = confidence_of(1, {"experience"})
    general_conf, _ = confidence_of(1, {"general"})

    assert skills_conf > experience_conf > general_conf


def test_the_highest_priority_section_wins():
    _, source = confidence_of(1, {"general", "experience", "skills"})

    assert source == ResumeSkill.Source.SKILLS_SECTION


def test_repeated_mentions_raise_confidence():
    once, _ = confidence_of(1, {"experience"})
    twice, _ = confidence_of(2, {"experience"})
    thrice, _ = confidence_of(3, {"experience"})

    assert once < twice < thrice


def test_confidence_never_exceeds_one():
    confidence, _ = confidence_of(50, {"skills"})

    assert confidence <= 1.0


def test_an_unrecognised_section_is_treated_as_general():
    confidence, source = confidence_of(1, {"nonsense"})

    assert confidence == 0.40
    assert source == ResumeSkill.Source.GENERAL


# --------------------------------------------------------------------------
# ATS scoring
# --------------------------------------------------------------------------


def full_resume_args():
    sections = detect(RESUME)
    contact = contact_of(RESUME)
    skills = [{"skill_id": i} for i in range(5)]
    # Padded to clear the 200-word floor without changing the structure
    text = RESUME + " padding" * 250
    return text, sections, contact, skills


def test_a_complete_resume_scores_highly():
    score, breakdown = ats_of(*full_resume_args())

    assert score >= 90
    assert breakdown["text_extractable"]["passed"] is True
    assert breakdown["sections"]["passed"] is True
    assert breakdown["contact"]["passed"] is True


@pytest.mark.regression
def test_an_image_only_pdf_loses_the_largest_block():
    """
    Text extraction is worth 40 of 100 because an ATS that cannot read the
    file rejects it outright - nothing else about the resume matters.
    """
    score, breakdown = ats_of("", {}, {}, [])

    assert breakdown["text_extractable"]["score"] == 0
    assert "image-based" in breakdown["text_extractable"]["reason"]
    assert score < 40


def test_a_too_short_resume_is_marked_down():
    _, breakdown = ats_of("word " * 50, {}, {}, [])

    assert breakdown["word_count"]["passed"] is False
    assert "too short" in breakdown["word_count"]["reason"]


def test_a_too_long_resume_is_marked_down():
    _, breakdown = ats_of("word " * 3000, {}, {}, [])

    assert breakdown["word_count"]["passed"] is False
    assert "too long" in breakdown["word_count"]["reason"]


def test_more_sections_earn_more_points():
    text = "word " * 400
    one = ats_of(text, {"skills": ""}, {}, [])[1]["sections"]["score"]
    three = ats_of(
        text,
        {"skills": "", "experience": "", "education": ""},
        {},
        [],
    )[1][
        "sections"
    ]["score"]

    assert three > one


def test_an_email_is_worth_more_than_a_phone_number():
    """Recruiters reply by email; the phone is a bonus."""
    text = "word " * 400
    email_only = ats_of(text, {}, {"email": "a@b.com"}, [])[1]["contact"]
    phone_only = ats_of(text, {}, {"phone": "9876543210"}, [])[1]["contact"]

    assert email_only["score"] > phone_only["score"]
    assert email_only["passed"] is True
    assert phone_only["passed"] is False


@pytest.mark.parametrize(
    "skill_count,expected",
    [
        (0, 0),
        (1, 4),
        (3, 7),
        (5, 10),
        (20, 10),
    ],
)
def test_skill_points_by_count(skill_count, expected):
    text = "word " * 400
    skills = [{"skill_id": i} for i in range(skill_count)]

    breakdown = ats_of(text, {}, {}, skills)[1]

    assert breakdown["skills_detected"]["score"] == expected


def test_the_score_never_exceeds_100():
    score, _ = ats_of(*full_resume_args())

    assert score <= 100


def test_an_empty_resume_scores_zero():
    score, _ = ats_of("", {}, {}, [])

    assert score == 5  # the word-count floor is the only thing that survives


def test_every_check_reports_its_maximum():
    """The breakdown is shown to the user, so each row needs its ceiling."""
    _, breakdown = ats_of(*full_resume_args())

    assert sum(check["max"] for check in breakdown.values()) == 100
