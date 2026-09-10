"""
Pure functions for learning recommendation logic.

Like algorithm.py, nothing here touches the database, so every function can be
unit tested with plain stub objects.
"""

from typing import Dict, List, Optional, Set

# Importance weights, kept in sync with algorithm.py (Feature 12)
IMPORTANCE_WEIGHTS = {
    "critical": 1.0,
    "important": 0.7,
    "preferred": 0.4,
    "optional": 0.2,
}

# Which resource difficulties suit a user at a given skill level.
# A user with no exposure should not be handed an advanced course.
DIFFICULTY_LADDER = {
    None: ["beginner"],
    "beginner": ["beginner", "intermediate"],
    "intermediate": ["intermediate", "advanced"],
    "advanced": ["advanced", "expert"],
    "expert": ["expert"],
}


def rank_resources(resources: List, user_completed_ids: Optional[Set[int]] = None):
    """
    Sort resources by curator endorsement first, then by quality score.
    Resources the user has already completed are dropped.
    """
    user_completed_ids = user_completed_ids or set()

    candidates = [r for r in resources if r.id not in user_completed_ids]

    return sorted(
        candidates,
        key=lambda r: (
            -1 if r.is_endorsed else 0,
            -r.quality_score,
        ),
    )


def filter_by_difficulty(resources: List, user_skill_level: Optional[str] = None):
    """
    Keep only the resources whose difficulty matches the user's current level.

    user_skill_level is None when the user has no exposure to the skill at all.
    """
    levels = DIFFICULTY_LADDER.get(user_skill_level, ["beginner"])
    return [r for r in resources if r.difficulty in levels]


def prioritize_skills(
    missing_critical: List[Dict],
    missing_important: List[Dict],
    missing_preferred: List[Dict],
) -> List[Dict]:
    """
    Order skills by importance, and by learning effort within each importance
    band, so the user always gets an achievable win before a long slog.
    """
    difficulty_order = {"easy": 0, "medium": 1, "hard": 2}

    def sort_within(skills):
        return sorted(
            skills,
            key=lambda s: difficulty_order.get(s.get("difficulty", "medium"), 1),
        )

    ordered = []
    ordered.extend(sort_within(missing_critical))
    ordered.extend(sort_within(missing_important))
    ordered.extend(sort_within(missing_preferred))
    return ordered


def cap_recommendations(
    skill_resources_list: List[Dict],
    max_per_skill: int = 3,
    total_max: int = 15,
) -> List[Dict]:
    """
    Limit how much is returned so the user is not overwhelmed.

    skill_resources_list: [{'skill': {...}, 'resources': [...]}, ...]
    """
    capped = []
    total = 0

    for item in skill_resources_list:
        if total >= total_max:
            break

        item_resources = item["resources"][:max_per_skill]
        if not item_resources:
            continue

        capped.append({**item, "resources": item_resources})
        total += len(item_resources)

    return capped
