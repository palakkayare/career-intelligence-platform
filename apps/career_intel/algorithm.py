"""
Pure functions for skill gap analysis.

Nothing here touches the database, so every function can be unit tested
with plain mock objects.
"""

from typing import Dict, List, Set

# Importance -> weight mapping used by the scoring formula
IMPORTANCE_WEIGHTS = {
    "critical": 1.0,
    "important": 0.7,
    "preferred": 0.4,
    "optional": 0.2,
}

DEFAULT_WEIGHT = 0.5


def compute_gap_score(
    seeker_skill_ids: Set[int],
    target_role_skills: List,  # list of TargetRoleSkill-like objects
) -> float:
    """
    Calculate the weighted gap score.

    0 = perfect fit, 100 = every required skill is missing.
    Lower is better.
    """
    if not target_role_skills:
        return 0.0

    total_weight = 0.0
    missing_weight = 0.0

    for trs in target_role_skills:
        weight = IMPORTANCE_WEIGHTS.get(trs.importance, DEFAULT_WEIGHT)
        total_weight += weight
        if trs.skill_id not in seeker_skill_ids:
            missing_weight += weight

    if total_weight == 0:
        return 0.0

    return round(missing_weight / total_weight * 100, 2)


def categorize_gap(gap_score: float) -> str:
    """Convert the numeric gap score into a descriptive label."""
    if gap_score == 0:
        return "perfect_fit"
    if gap_score < 20:
        return "ready"
    if gap_score < 40:
        return "close"
    if gap_score < 60:
        return "developing"
    return "significant"


def split_skills(seeker_skill_ids: Set[int], target_role_skills: List) -> Dict:
    """
    Split required skills into matched and missing buckets.

    Returns:
        {
            'matched': [...],
            'missing_critical': [...],
            'missing_important': [...],
            'missing_preferred': [...],
            'missing_optional': [...],
        }
    """
    result = {
        "matched": [],
        "missing_critical": [],
        "missing_important": [],
        "missing_preferred": [],
        "missing_optional": [],
    }

    for trs in target_role_skills:
        skill_data = {
            "skill_id": trs.skill_id,
            "skill_name": trs.skill.name,
            "importance": trs.importance,
            "difficulty": trs.difficulty,
            "rationale": trs.rationale,
        }

        if trs.skill_id in seeker_skill_ids:
            result["matched"].append(skill_data)
        else:
            bucket = f"missing_{trs.importance}"
            if bucket in result:
                result[bucket].append(skill_data)

    return result


def prioritize_recommendations(split: Dict, max_count: int = 5) -> List[Dict]:
    """
    Suggest the top N skills to learn next, ordered so the user always
    gets an achievable win first.

    Priority:
        1. Critical + Easy    -> start here
        2. Critical + Medium  -> next
        3. Important + Easy   -> quick wins
        4. Critical + Hard    -> long-term projects
        5. Important + Medium -> fill in the rest
    """
    priority_order = [
        ("missing_critical", "easy"),
        ("missing_critical", "medium"),
        ("missing_important", "easy"),
        ("missing_critical", "hard"),
        ("missing_important", "medium"),
        ("missing_important", "hard"),
        ("missing_preferred", "easy"),
        ("missing_preferred", "medium"),
    ]

    recommendations = []

    for bucket, difficulty in priority_order:
        for skill in split.get(bucket, []):
            if skill["difficulty"] == difficulty:
                recommendations.append(
                    {
                        "skill_id": skill["skill_id"],
                        "skill_name": skill["skill_name"],
                        "importance": skill["importance"],
                        "difficulty": skill["difficulty"],
                        "reason": _build_reason(skill, bucket, difficulty),
                    }
                )
                if len(recommendations) >= max_count:
                    return recommendations

    return recommendations


def _build_reason(skill: Dict, bucket: str, difficulty: str) -> str:
    """Build the human-readable suggestion text for one recommendation."""
    importance = bucket.replace("missing_", "")
    name = skill["skill_name"]

    if importance == "critical" and difficulty == "easy":
        return f"Start here - {name} is critical and easy to learn."
    if importance == "critical" and difficulty == "medium":
        return f"{name} is critical for this role. Plan for 1-2 months."
    if importance == "critical" and difficulty == "hard":
        return f"{name} is critical but takes time. Plan for 3+ months."
    if importance == "important" and difficulty == "easy":
        return f"Quick win - {name} is important and easy to add."
    if importance == "important":
        return f"{name} is strongly preferred for this role."

    return f"{name} would strengthen your profile."
