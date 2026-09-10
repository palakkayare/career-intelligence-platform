"""
Advanced ATS analysis.

These are pure functions with no database or external service behind them,
so the tests need no django_db mark and run in milliseconds.

Scores are asserted as ranges and relationships rather than exact numbers
wherever the exact value is a tuning decision. A test that pins
`score == 17` fails every time someone adjusts a weight, which trains people
to update the number instead of thinking about whether the change was right.
"""

import pytest

from apps.resumes.ats_advanced import (
    MIN_ANALYSABLE_LENGTH,
    _rating_for,
    _split_into_bullets,
    analyze_action_verbs,
    analyze_jd_match,
    analyze_language_quality,
    analyze_quantification,
    extract_jd_keywords,
    run_full_analysis,
)

STRONG_RESUME = """
Senior Backend Engineer

• Led a team of 6 engineers to deliver a payments platform
• Built and shipped a resume parsing service handling 40,000 documents
• Optimized database queries and reduced p95 latency by 45%
• Designed the matching algorithm that increased applications by 23%
• Mentored 3 junior developers and coordinated the hiring loop
• Analyzed churn data and identified 4 retention opportunities
"""

WEAK_RESUME = """
Backend Developer

• Responsible for the payments system and its maintenance
• Duties included working on the resume feature with the team
• Helped with database work and assisted with query tuning
• Was tasked with looking after the matching logic
• Involved in various team activities and meetings
"""


# --------------------------------------------------------------------------
# Action verbs
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_strong_verbs_are_found_and_categorised():
    """
    Regression: ats_advanced.py is 204 lines of scoring logic behind a paid
    feature and had no test at all.
    """
    result = analyze_action_verbs(STRONG_RESUME)

    assert result["unique_strong_count"] > 5
    assert "leadership" in result["categories_used"]
    assert "building" in result["categories_used"]
    assert "improvement" in result["categories_used"]
    assert result["weak_phrases_found"] == []


def test_weak_phrases_are_penalised():
    strong = analyze_action_verbs(STRONG_RESUME)
    weak = analyze_action_verbs(WEAK_RESUME)

    assert weak["weak_phrases_found"], "filler phrases should be detected"
    assert weak["score"] < strong["score"]


def test_verb_matching_is_case_insensitive():
    assert analyze_action_verbs("Led the team")["unique_strong_count"] == 1
    assert analyze_action_verbs("LED THE TEAM")["unique_strong_count"] == 1


def test_verbs_match_whole_words_only():
    """'led' must not fire on 'called' or 'settled'."""
    result = analyze_action_verbs("I called the client and settled the issue")

    assert result["unique_strong_count"] == 0


def test_score_stays_within_bounds():
    for text in (STRONG_RESUME, WEAK_RESUME, "", "a" * 500):
        result = analyze_action_verbs(text)
        assert 0 <= result["score"] <= 25


def test_a_resume_full_of_filler_cannot_go_negative():
    text = " ".join(["responsible for the thing."] * 20)

    assert analyze_action_verbs(text)["score"] == 0


def test_variety_across_categories_is_rewarded():
    """Six different kinds of verb should beat one verb repeated."""
    varied = analyze_action_verbs(
        "Led the team. Built the service. Optimized the queries. "
        "Delivered the release. Analyzed the data. Collaborated with design."
    )
    repeated = analyze_action_verbs("Led. Led. Led. Led. Led. Led.")

    assert varied["score"] > repeated["score"]
    assert len(varied["categories_used"]) >= 4


def test_suggestions_appear_when_verbs_are_thin():
    result = analyze_action_verbs("I worked on things.")

    assert result["suggestions"]


# --------------------------------------------------------------------------
# Quantification
# --------------------------------------------------------------------------


def test_numbers_in_bullets_are_detected():
    result = analyze_quantification(STRONG_RESUME)

    assert result["quantified_count"] > 0
    assert result["pct_quantified"] > 0
    assert result["examples"]


def test_a_resume_with_no_numbers_scores_zero():
    result = analyze_quantification(WEAK_RESUME)

    assert result["quantified_count"] == 0
    assert result["score"] == 0


def test_more_numbers_means_a_higher_score():
    few = analyze_quantification(
        """
        • Led the backend team through a platform migration
        • Built the resume parsing service from scratch
        • Optimized the slowest database queries in the system
        • Reduced signup drop-off by 25% over one quarter
    """
    )
    many = analyze_quantification(
        """
        • Led a team of 6 through a platform migration
        • Built a parser handling 40,000 documents a month
        • Optimized queries and cut p95 latency by 45%
        • Reduced signup drop-off by 25% over one quarter
    """
    )

    assert many["score"] > few["score"]


def test_empty_text_is_handled():
    result = analyze_quantification("")

    assert result["score"] == 0
    assert result["total_bullets"] == 0
    assert result["suggestions"]


def test_bullets_are_preferred_over_sentences():
    bulleted = _split_into_bullets(
        """
        • Led the backend team through a migration
        • Built the resume parsing service end to end
        • Optimized the slowest queries in the system
        • Reduced signup drop-off by a quarter
    """
    )

    assert len(bulleted) == 4


def test_prose_falls_back_to_sentences():
    """Plain-text exports often lose their bullet characters entirely."""
    result = _split_into_bullets(
        "I led the backend team through a migration. "
        "I built the resume parsing service. "
        "I optimized the slowest queries in the system."
    )

    assert len(result) >= 3


# --------------------------------------------------------------------------
# Language quality
# --------------------------------------------------------------------------


def test_passive_voice_is_detected():
    passive = analyze_language_quality(
        "The system was designed by the team. "
        "The migration was completed by me. "
        "The report was written by the analyst."
    )

    assert passive["passive_voice"]["count"] > 0
    assert passive["passive_voice"]["pct"] > 0


def test_active_voice_scores_higher_than_passive():
    active = analyze_language_quality(
        "I designed the system. I completed the migration. I wrote the report."
    )
    passive = analyze_language_quality(
        "The system was designed by me. The migration was completed by me. "
        "The report was written by me."
    )

    assert active["score"] > passive["score"]


def test_language_score_stays_within_bounds():
    for text in (STRONG_RESUME, WEAK_RESUME, ""):
        assert 0 <= analyze_language_quality(text)["score"] <= 20


# --------------------------------------------------------------------------
# Job description matching
# --------------------------------------------------------------------------

SKILLS = {"Python", "Django", "PostgreSQL", "Redis", "Celery", "React"}


def test_jd_keywords_come_from_the_skill_database():
    """Raw word splitting would turn 'Python.' and 'Python,' into keywords."""
    result = extract_jd_keywords(
        "We need Python, Django and PostgreSQL experience.",
        SKILLS,
    )

    assert set(result["skills"]) == {"Python", "Django", "PostgreSQL"}


def test_required_years_and_qualifications_are_extracted():
    result = extract_jd_keywords(
        "Bachelor's degree required with 5+ years of experience in Python.",
        SKILLS,
    )

    assert result["required_years"] == 5
    assert result["qualifications"]


def test_a_full_skill_match_scores_highest():
    result = analyze_jd_match(
        resume_text="I work with Python, Django and PostgreSQL daily.",
        jd_text="Looking for Python, Django and PostgreSQL experience.",
        skill_names=SKILLS,
    )

    assert result["scorable"] is True
    assert result["skill_match_pct"] == 100.0
    assert result["score"] == 30
    assert result["missing_skills"] == []


def test_missing_skills_are_reported():
    result = analyze_jd_match(
        resume_text="I work with Python.",
        jd_text="We need Python, Django, PostgreSQL, Redis and Celery.",
        skill_names=SKILLS,
    )

    assert "Python" in result["matched_skills"]
    assert "Django" in result["missing_skills"]
    assert result["suggestions"]


@pytest.mark.regression
def test_a_vague_job_description_is_not_scored():
    """
    A posting with no recognisable skills cannot be scored honestly, and
    scoring it anyway would punish the candidate for the employer's writing.
    """
    result = analyze_jd_match(
        resume_text="I work with Python and Django.",
        jd_text="We want a rockstar who thrives in a fast-paced environment.",
        skill_names=SKILLS,
    )

    assert result["scorable"] is False
    assert result["score"] == 0


# --------------------------------------------------------------------------
# Ratings
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pct,grade",
    [
        (100, "A"),
        (85, "A"),
        (84, "B"),
        (70, "B"),
        (69, "C"),
        (55, "C"),
        (54, "D"),
        (40, "D"),
        (39, "F"),
        (0, "F"),
    ],
)
def test_rating_boundaries(pct, grade):
    assert _rating_for(pct).startswith(grade)


# --------------------------------------------------------------------------
# Full analysis
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_short_text_returns_the_same_shape_as_a_real_result():
    """
    The Celery task reads advanced_score_pct unconditionally. A short-circuit
    return that dropped the key would raise KeyError in a background worker,
    where nobody would see it.
    """
    result = run_full_analysis("too short")

    assert result["analysable"] is False
    assert result["advanced_score_pct"] == 0.0
    assert result["rating"]
    assert result["top_suggestions"]
    assert "breakdown" in result


def test_analysis_without_a_job_description_is_out_of_70():
    result = run_full_analysis(STRONG_RESUME)

    assert result["analysable"] is True
    assert result["advanced_max"] == 70
    assert result["has_jd_analysis"] is False
    assert "jd_match" not in result["breakdown"]


def test_a_job_description_raises_the_ceiling_to_100():
    result = run_full_analysis(
        STRONG_RESUME,
        jd_text="We need Python, Django and PostgreSQL.",
        skill_names=SKILLS,
    )

    assert result["advanced_max"] == 100
    assert result["has_jd_analysis"] is True
    assert "jd_match" in result["breakdown"]


@pytest.mark.regression
def test_a_vague_jd_does_not_lower_the_ceiling():
    """
    An unscorable JD must contribute neither points nor maximum, or a vague
    posting would drag the percentage down through no fault of the candidate.
    """
    result = run_full_analysis(
        STRONG_RESUME,
        jd_text="Rockstar wanted. Must be a self-starter.",
        skill_names=SKILLS,
    )

    assert result["advanced_max"] == 70
    assert result["has_jd_analysis"] is True


def test_a_strong_resume_outscores_a_weak_one():
    strong = run_full_analysis(STRONG_RESUME)
    weak = run_full_analysis(WEAK_RESUME)

    assert strong["advanced_score_pct"] > weak["advanced_score_pct"]


def test_suggestions_are_capped_at_five():
    """A long list of fixes makes people do nothing."""
    result = run_full_analysis(WEAK_RESUME)

    assert len(result["top_suggestions"]) <= 5


def test_the_length_threshold_is_respected():
    just_under = "word " * (MIN_ANALYSABLE_LENGTH // 5 - 5)
    comfortably_over = STRONG_RESUME

    assert run_full_analysis(just_under)["analysable"] is False
    assert run_full_analysis(comfortably_over)["analysable"] is True
