"""
Match score algorithm.

Pure functions, no database. This is the code that decides what every seeker
sees on every job, recomputed for every pair every six hours - a bug here is
invisible and affects everyone at once, which is exactly the kind of thing
tests are for.

Weights come from the blueprint: skills 60%, experience 20%, location 10%,
salary 10%.
"""

import pytest

from apps.match_scores.algorithm import (
    EXPECTED_SALARY_RANGES,
    WEIGHTS,
    compute_experience_score,
    compute_location_score,
    compute_overall_score,
    compute_salary_score,
    compute_skills_score,
)

LAKH = 100_000


# --------------------------------------------------------------------------
# Weighting
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_weights_match_the_blueprint():
    """
    Regression: the whole matching module sat at 14% coverage. The weights
    are a documented product decision (Feature 11), not an implementation
    detail someone should be able to nudge unnoticed.
    """
    assert WEIGHTS["skills"] == 0.60
    assert WEIGHTS["experience"] == 0.20
    assert WEIGHTS["location"] == 0.10
    assert WEIGHTS["salary"] == 0.10
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_a_perfect_match_scores_100():
    assert compute_overall_score(100, 100, 100, 100) == pytest.approx(100)


def test_a_total_mismatch_scores_zero():
    assert compute_overall_score(0, 0, 0, 0) == 0


def test_skills_dominate_the_result():
    """Skills at 60% must outweigh everything else combined."""
    skills_only = compute_overall_score(100, 0, 0, 0)
    everything_else = compute_overall_score(0, 100, 100, 100)

    assert skills_only > everything_else


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------


def test_every_required_skill_matched_scores_100():
    result = compute_skills_score({1, 2, 3}, {1, 2, 3}, set())

    assert result["score"] == 100.0
    assert result["missing_required"] == []
    assert result["required_match_count"] == 3


def test_half_the_required_skills_scores_about_half():
    result = compute_skills_score({1, 2}, {1, 2, 3, 4}, set())

    assert result["score"] == 50.0
    assert sorted(result["missing_required"]) == [3, 4]


def test_no_matching_skills_scores_zero():
    assert compute_skills_score({9, 8}, {1, 2, 3}, set())["score"] == 0.0


def test_nice_to_have_skills_add_a_bonus():
    without = compute_skills_score({1, 2}, {1, 2, 3, 4}, set())
    with_nice = compute_skills_score({1, 2, 7}, {1, 2, 3, 4}, {7})

    assert with_nice["score"] > without["score"]
    assert with_nice["matched_nice"] == [7]


def test_the_nice_to_have_bonus_is_capped():
    """Ten bonus skills must not paper over missing required ones."""
    nice = {10, 11, 12, 13, 14, 15}
    result = compute_skills_score({1} | nice, {1, 2, 3, 4}, nice)

    # 25% required + capped 20 bonus, not 25 + 30
    assert result["score"] == 45.0


def test_the_score_never_exceeds_100():
    nice = {10, 11, 12, 13}
    result = compute_skills_score({1, 2} | nice, {1, 2}, nice)

    assert result["score"] == 100.0


def test_a_job_with_no_required_skills_gets_a_neutral_score():
    """
    Scoring 0 would punish the seeker for the recruiter leaving the field
    blank; scoring 100 would make every such job a perfect match.
    """
    result = compute_skills_score({1, 2, 3}, set(), set())

    assert result["score"] == 50.0


# --------------------------------------------------------------------------
# Experience
# --------------------------------------------------------------------------


def test_experience_inside_the_range_is_a_perfect_fit():
    result = compute_experience_score(seeker_years=4, job_min_years=3, job_max_years=6)

    assert result["score"] == 100.0
    assert result["fit"] == "perfect"


@pytest.mark.parametrize("years", [3, 6])
def test_the_range_boundaries_are_inclusive(years):
    result = compute_experience_score(years, job_min_years=3, job_max_years=6)

    assert result["fit"] == "perfect"


def test_under_qualification_costs_20_points_a_year():
    result = compute_experience_score(seeker_years=1, job_min_years=3, job_max_years=6)

    assert result["fit"] == "under_qualified"
    assert result["gap_years"] == 2
    assert result["score"] == 60.0


def test_a_large_experience_gap_floors_at_zero():
    result = compute_experience_score(seeker_years=0, job_min_years=15)

    assert result["score"] == 0.0


def test_over_qualification_is_penalised_gently():
    """Too much experience is a much smaller problem than too little."""
    under = compute_experience_score(1, job_min_years=5, job_max_years=8)
    over = compute_experience_score(12, job_min_years=5, job_max_years=8)

    assert over["fit"] == "over_qualified"
    assert over["score"] > under["score"]


def test_over_qualification_never_drops_below_50():
    result = compute_experience_score(seeker_years=40, job_min_years=1, job_max_years=2)

    assert result["score"] == 50.0


def test_a_missing_upper_bound_gets_a_sensible_default():
    """An open-ended requirement should not make everyone over-qualified."""
    result = compute_experience_score(seeker_years=8, job_min_years=3)

    assert result["fit"] == "perfect"
    assert "3-13" in result["required_range"]


# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------


def test_remote_ignores_location_entirely():
    result = compute_location_score("Pune", "Bangalore", "remote")

    assert result["score"] == 100.0


def test_the_same_city_scores_full_marks():
    result = compute_location_score("Bangalore", "Bangalore", "onsite")

    assert result["score"] == 100.0
    assert result["reason"] == "Same city"


def test_city_matching_ignores_case_and_state_suffix():
    result = compute_location_score(
        "bangalore, karnataka",
        "Bangalore, KA",
        "onsite",
    )

    assert result["score"] == 100.0


def test_hybrid_across_cities_beats_onsite_across_cities():
    hybrid = compute_location_score("Pune", "Bangalore", "hybrid")
    onsite = compute_location_score("Pune", "Bangalore", "onsite")

    assert hybrid["score"] == 60.0
    assert onsite["score"] == 30.0


def test_missing_location_gets_a_neutral_score():
    """An unfilled profile field is not evidence of a bad match."""
    assert compute_location_score("", "Bangalore", "onsite")["score"] == 50.0
    assert compute_location_score("Pune", "", "onsite")["score"] == 50.0


# --------------------------------------------------------------------------
# Salary
# --------------------------------------------------------------------------


def test_an_undisclosed_salary_gets_a_mild_benefit_of_the_doubt():
    result = compute_salary_score(seeker_years=3, job_min_inr=0, job_max_inr=0)

    assert result["score"] == 70.0
    assert "not disclosed" in result["reason"]


def test_a_salary_in_the_expected_band_scores_well():
    # 3 years experience -> expected 8-18 LPA
    result = compute_salary_score(3, 10 * LAKH, 15 * LAKH)

    assert result["score"] == 90.0
    assert "aligns" in result["reason"]


def test_a_salary_above_expectation_scores_full_marks():
    result = compute_salary_score(3, 30 * LAKH, 40 * LAKH)

    assert result["score"] == 100.0


def test_an_underpaying_job_is_penalised_by_how_far_below_it_is():
    slightly_low = compute_salary_score(3, 5 * LAKH, 7 * LAKH)
    very_low = compute_salary_score(3, 1 * LAKH, 2 * LAKH)

    assert very_low["score"] < slightly_low["score"]
    assert very_low["score"] >= 0


@pytest.mark.parametrize(
    "years,expected_band",
    [
        (0, (3, 8)),
        (1, (3, 8)),
        (2, (8, 18)),
        (4, (8, 18)),
        (5, (18, 40)),
        (9, (18, 40)),
        (10, (40, 80)),
        (25, (60, 150)),
    ],
)
def test_expected_band_by_experience(years, expected_band):
    """Band boundaries are exclusive at the top, so 2 years is mid, not junior."""
    result = compute_salary_score(years, 1 * LAKH, 2 * LAKH)

    low, high = expected_band
    assert result["expected_range"] == f"₹{low}-{high} LPA"


def test_an_implausible_experience_value_falls_back_to_junior():
    """
    Nothing in EXPECTED_SALARY_RANGES covers 200 years. The loop leaves the
    default in place rather than raising, which is the right behaviour for
    a bad profile value.
    """
    result = compute_salary_score(200, 1 * LAKH, 2 * LAKH)

    assert result["expected_range"] == "₹3-8 LPA"


def test_the_salary_bands_are_continuous():
    """A gap between bands would silently drop seekers to the junior default."""
    boundaries = sorted(EXPECTED_SALARY_RANGES.keys())
    for (_, upper), (lower_next, _) in zip(boundaries, boundaries[1:]):
        assert upper == lower_next, f"gap between {upper} and {lower_next}"


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


def test_an_ideal_candidate_scores_near_the_top():
    skills = compute_skills_score({1, 2, 3}, {1, 2, 3}, set())
    experience = compute_experience_score(4, 3, 6)
    location = compute_location_score("Bangalore", "Bangalore", "onsite")
    salary = compute_salary_score(4, 10 * LAKH, 15 * LAKH)

    overall = compute_overall_score(
        skills["score"],
        experience["score"],
        location["score"],
        salary["score"],
    )

    assert overall >= 95


def test_a_poor_candidate_scores_low():
    skills = compute_skills_score({9}, {1, 2, 3}, set())
    experience = compute_experience_score(0, 8)
    location = compute_location_score("Pune", "Bangalore", "onsite")
    salary = compute_salary_score(0, 1 * LAKH, 2 * LAKH)

    overall = compute_overall_score(
        skills["score"],
        experience["score"],
        location["score"],
        salary["score"],
    )

    assert overall < 20


@pytest.mark.regression
def test_skills_alone_cannot_carry_a_bad_match_to_the_top():
    """
    A candidate with every skill but nothing else in their favour should
    land around 60, not near 100 - that is what the 60% weight means.
    """
    overall = compute_overall_score(100, 0, 0, 0)

    assert 55 <= overall <= 65
