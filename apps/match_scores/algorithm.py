"""
Pure functions for match score computation.
No DB writes here — just calculations.
"""

from typing import Dict, Set

# Weights (must sum to 1.0)
WEIGHTS = {
    "skills": 0.60,
    "experience": 0.20,
    "location": 0.10,
    "salary": 0.10,
}


def compute_overall_score(
    skills: float, experience: float, location: float, salary: float
) -> float:
    """Combine component scores using weights."""
    return (
        skills * WEIGHTS["skills"]
        + experience * WEIGHTS["experience"]
        + location * WEIGHTS["location"]
        + salary * WEIGHTS["salary"]
    )


# ─── Skills Matching ───


def compute_skills_score(
    seeker_skill_ids: Set[int],
    required_skill_ids: Set[int],
    nice_to_have_ids: Set[int],
) -> Dict:
    """
    Skills match score (0-100).
    Required skills are critical — base score comes from them.
    Nice-to-have skills give a bonus (up to 20 pts).
    """
    if not required_skill_ids:
        return {
            "score": 50.0,
            "matched_required": [],
            "missing_required": [],
            "matched_nice": [],
        }

    matched_required = seeker_skill_ids & required_skill_ids
    missing_required = required_skill_ids - seeker_skill_ids
    matched_nice = seeker_skill_ids & nice_to_have_ids

    # Required match percentage
    required_pct = len(matched_required) / len(required_skill_ids) * 100

    # Nice-to-have bonus (5 pts each, capped at 20)
    nice_bonus = min(20, len(matched_nice) * 5)

    final_score = min(100.0, required_pct + nice_bonus)

    return {
        "score": round(final_score, 2),
        "matched_required": list(matched_required),
        "missing_required": list(missing_required),
        "matched_nice": list(matched_nice),
        "required_match_count": len(matched_required),
        "required_total_count": len(required_skill_ids),
    }


# ─── Experience Matching ───


def compute_experience_score(
    seeker_years: int,
    job_min_years: int,
    job_max_years=None,
) -> Dict:
    """
    Experience overlap score.
    Perfect fit = 100. Under-qualified = penalty per year. Over-qualified = mild penalty.
    """
    if job_max_years is None:
        job_max_years = job_min_years + 10  # Reasonable default upper bound

    if job_min_years <= seeker_years <= job_max_years:
        # Perfect fit — seeker's experience is within the job's required range
        return {
            "score": 100.0,
            "fit": "perfect",
            "seeker_years": seeker_years,
            "required_range": f"{job_min_years}-{job_max_years} years",
        }

    if seeker_years < job_min_years:
        # Under-qualified — 20 pts penalty per year of gap
        gap = job_min_years - seeker_years
        score = max(0.0, 100.0 - gap * 20)
        return {
            "score": round(score, 2),
            "fit": "under_qualified",
            "gap_years": gap,
            "seeker_years": seeker_years,
            "required_range": f"{job_min_years}-{job_max_years} years",
        }

    # Over-qualified (less critical) — 5 pts penalty per excess year, floor at 50
    excess = seeker_years - job_max_years
    score = max(50.0, 100.0 - excess * 5)
    return {
        "score": round(score, 2),
        "fit": "over_qualified",
        "excess_years": excess,
        "seeker_years": seeker_years,
        "required_range": f"{job_min_years}-{job_max_years} years",
    }


# ─── Location Matching ───


def compute_location_score(
    seeker_location: str,
    job_location: str,
    work_arrangement: str,
) -> Dict:
    """
    Location compatibility.
    Remote = 100. Same city = 100. Hybrid different city = 60. On-site different = 30.
    """
    if work_arrangement == "remote":
        return {
            "score": 100.0,
            "reason": "Remote — location flexible",
            "arrangement": "remote",
        }

    if not seeker_location or not job_location:
        return {
            "score": 50.0,
            "reason": "Location info incomplete",
            "arrangement": work_arrangement,
        }

    seeker_city = seeker_location.lower().split(",")[0].strip()
    job_city = job_location.lower().split(",")[0].strip()

    if seeker_city == job_city:
        return {
            "score": 100.0,
            "reason": "Same city",
            "seeker_city": seeker_city,
            "job_city": job_city,
        }

    if work_arrangement == "hybrid":
        return {
            "score": 60.0,
            "reason": "Hybrid — different cities, may need relocation",
            "seeker_city": seeker_city,
            "job_city": job_city,
        }

    # On-site, different city
    return {
        "score": 30.0,
        "reason": "On-site in different city",
        "seeker_city": seeker_city,
        "job_city": job_city,
    }


# ─── Salary Matching ───

# Reasonable expectation by experience level (Indian market, 2026)
EXPECTED_SALARY_RANGES = {
    # (min_years, max_years): (min_inr_lakhs, max_inr_lakhs)
    (0, 2): (3, 8),
    (2, 5): (8, 18),
    (5, 10): (18, 40),
    (10, 20): (40, 80),
    (20, 100): (60, 150),
}


def compute_salary_score(
    seeker_years: int,
    job_min_inr: float,
    job_max_inr: float,
) -> Dict:
    """
    Salary expectation overlap (heuristic based on experience).
    """
    if not job_min_inr or not job_max_inr:
        return {
            "score": 70.0,
            "reason": "Salary not disclosed by employer",
        }

    # Find expected salary range based on experience
    expected = (3, 8)  # Default: junior
    for (min_y, max_y), (min_lpa, max_lpa) in EXPECTED_SALARY_RANGES.items():
        if min_y <= seeker_years < max_y:
            expected = (min_lpa, max_lpa)
            break

    expected_min_inr = expected[0] * 100000
    expected_max_inr = expected[1] * 100000

    # Range overlap detection
    if job_max_inr < expected_min_inr:
        # Job offers less than expected — under-paying
        gap_pct = (expected_min_inr - job_max_inr) / expected_min_inr * 100
        score = max(0.0, 100 - gap_pct * 2)
        return {
            "score": round(score, 2),
            "reason": "Salary below market expectation",
            "expected_range": f"₹{expected[0]}-{expected[1]} LPA",
            "job_range": f"₹{job_min_inr/100000:.1f}-{job_max_inr/100000:.1f} LPA",
        }

    if job_min_inr > expected_max_inr:
        # Job offers more than expected (rare — usually over-qualified candidate)
        return {
            "score": 100.0,
            "reason": "Salary above expectation",
            "expected_range": f"₹{expected[0]}-{expected[1]} LPA",
            "job_range": f"₹{job_min_inr/100000:.1f}-{job_max_inr/100000:.1f} LPA",
        }

    # Overlap exists — job's range overlaps with seeker's expected range
    return {
        "score": 90.0,
        "reason": "Salary aligns with expectation",
        "expected_range": f"₹{expected[0]}-{expected[1]} LPA",
        "job_range": f"₹{job_min_inr/100000:.1f}-{job_max_inr/100000:.1f} LPA",
    }
