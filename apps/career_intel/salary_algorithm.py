"""
apps/career_intel/salary_algorithm.py

Pure functions for salary statistics and privacy helpers.

Deliberately free of Django imports: these are plain functions, so they can be
unit-tested in isolation without touching the database.
"""

from decimal import Decimal
from typing import Dict, List, Optional, Sequence

# Default sanity bounds for the Indian market (annual base, INR).
DEFAULT_MIN_INR = 100_000        # 1 Lakh floor  -> anything lower is a data entry error
DEFAULT_MAX_INR = 100_000_000    # 10 Crore ceiling -> anything higher needs verification


def calculate_percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """
    Return the `pct` percentile (0-100) of `values`.

    Uses linear interpolation between the two closest ranks, which is the same
    method numpy uses by default. Pure Python, so no numpy/scipy dependency.

    Returns None for an empty input.
    """
    if not values:
        return None

    sorted_vals = sorted(float(v) for v in values)
    n = len(sorted_vals)

    if n == 1:
        return sorted_vals[0]
    if pct <= 0:
        return sorted_vals[0]
    if pct >= 100:
        return sorted_vals[-1]

    rank = (pct / 100.0) * (n - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, n - 1)
    fraction = rank - lower_idx

    return sorted_vals[lower_idx] + fraction * (sorted_vals[upper_idx] - sorted_vals[lower_idx])


def calculate_median(values: Sequence[float]) -> Optional[float]:
    """Median, i.e. the 50th percentile."""
    return calculate_percentile(values, 50)


# Published figures are rounded to this band.
#
# The reason is not presentation. With five submissions a percentile lands
# exactly on a person: at n=5, p25 is values[1], the median is values[2] and
# p75 is values[3] - so the "aggregate" is one individual's exact salary.
# Rounding to a band means a published figure identifies a range rather than
# a person, which is what the anonymity promise actually requires.
#
# ₹50,000 is about 3% of a mid-level Indian salary: wide enough to hide an
# individual, narrow enough that the number still guides a negotiation.
PUBLISH_ROUNDING_INR = 50_000


def round_for_publication(value, band=PUBLISH_ROUNDING_INR):
    """
    Round a salary figure to the nearest band before it is published.

    Returns None unchanged so callers do not have to special-case an absent
    figure.
    """
    if value is None:
        return None

    return int(round(float(value) / band) * band)


def calculate_aggregates(salaries: Sequence[Decimal]) -> Optional[Dict]:
    """
    Compute aggregate statistics from a list of salaries.

    Returns a dict with count, min, max, mean, median and the p10/p25/p75/p90
    percentiles. Returns None if the input list is empty.

    NOTE: this function never returns anything that could identify a single
    submission -- only summary numbers.
    """
    if not salaries:
        return None

    floats = [float(s) for s in salaries]

    return {
        'count': len(floats),
        'min': min(floats),
        'max': max(floats),
        'mean': sum(floats) / len(floats),
        'median': calculate_median(floats),
        'p10': calculate_percentile(floats, 10),
        'p25': calculate_percentile(floats, 25),
        'p75': calculate_percentile(floats, 75),
        'p90': calculate_percentile(floats, 90),
    }


def trim_outliers_simple(
    salaries: Sequence[Decimal],
    min_inr: float = DEFAULT_MIN_INR,
    max_inr: float = DEFAULT_MAX_INR,
) -> List[Decimal]:
    """
    Drop values that fall outside a sane range for the Indian market.

    This is the Phase 3 approach: a simple hard cap. Phase 4 replaces it with
    the IQR-based version below.
    """
    return [s for s in salaries if min_inr <= float(s) <= max_inr]


def trim_outliers_iqr(salaries: Sequence[Decimal], multiplier: float = 1.5) -> List[Decimal]:
    """
    Drop statistical outliers using the interquartile range (IQR) rule.

    Any value below Q1 - multiplier*IQR or above Q3 + multiplier*IQR is
    discarded. Kept here for Phase 4; not wired into the service yet.

    With very few data points the IQR is unstable, so the input is returned
    untouched when there are fewer than 4 values.
    """
    if len(salaries) < 4:
        return list(salaries)

    floats = [float(s) for s in salaries]
    q1 = calculate_percentile(floats, 25)
    q3 = calculate_percentile(floats, 75)
    iqr = q3 - q1
    lower_bound = q1 - multiplier * iqr
    upper_bound = q3 + multiplier * iqr

    return [s for s in salaries if lower_bound <= float(s) <= upper_bound]


def format_inr_lpa(inr_amount: Optional[float]) -> Optional[str]:
    """Convert a raw INR figure into a display string, e.g. 1850000 -> '₹18.5 LPA'."""
    if inr_amount is None:
        return None
    lpa = float(inr_amount) / 100_000
    return f"₹{lpa:.1f} LPA"


def determine_market_position(user_salary, percentiles: Dict) -> str:
    """
    Compare a single salary against the market percentiles.

    Returns one of: 'below_market', 'fair_market', 'above_market', 'top_of_market'.
    """
    user_val = float(user_salary)

    if user_val < percentiles['p25']:
        return 'below_market'
    if user_val < percentiles['p75']:
        return 'fair_market'
    if user_val < percentiles['p90']:
        return 'above_market'
    return 'top_of_market'


def market_position_message(position: str, user_salary, percentiles: Dict) -> str:
    """Build a short, human-readable summary of the user's market position."""
    user_val = float(user_salary)
    median = percentiles.get('median') or 0

    # Guard against a division by zero if the median is somehow 0.
    diff_pct = ((user_val - median) / median * 100) if median else 0

    messages = {
        'below_market': (
            f"Your salary is below the 25th percentile. "
            f"The market median is ₹{median / 100000:.1f}L and you are at "
            f"₹{user_val / 100000:.1f}L ({abs(diff_pct):.0f}% below the median). "
            f"This may be worth negotiating."
        ),
        'fair_market': (
            f"Your salary sits in the fair range, between the 25th and 75th percentile. "
            f"The market median is ₹{median / 100000:.1f}L."
        ),
        'above_market': (
            f"You are paid above market. The 75th percentile is "
            f"₹{percentiles['p75'] / 100000:.1f}L and you are at ₹{user_val / 100000:.1f}L."
        ),
        'top_of_market': (
            f"Top earner. You are in the top 10%: the 90th percentile is "
            f"₹{percentiles['p90'] / 100000:.1f}L."
        ),
    }

    return messages.get(position, "Market position calculated.")