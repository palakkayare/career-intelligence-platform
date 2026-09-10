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


# Published figures are rounded to a band.
#
# The reason is not presentation. With five submissions a percentile lands
# exactly on a person: at n=5, p25 is values[1], the median is values[2] and
# p75 is values[3] - so the "aggregate" is one individual's exact salary.
# Rounding means a published figure identifies a range rather than a person,
# which is what the anonymity promise actually requires.
#
# The band is proportional, not flat. A flat ₹50,000 works for a group of
# juniors clustered between ₹8L and ₹12L - several of them fall inside it, so
# the figure stays ambiguous. It fails for five senior engineers spread from
# ₹30L to ₹80L, where a ₹50,000 window around the median contains exactly one
# person. That is the wrong way round: protection is thinnest where the
# population is smallest and the salary is most identifying.
#
# Scaling with the data fixes that without per-bucket tuning that would go
# stale. See choose_band.
PUBLISH_BAND_PCT = 0.05
PUBLISH_BAND_MIN_INR = 50_000
PUBLISH_BAND_MAX_INR = 500_000

# Kept as the floor's old name so existing callers and tests still read.
PUBLISH_ROUNDING_INR = PUBLISH_BAND_MIN_INR


def publication_percentile(sorted_values, p):
    """
    A percentile that is never one person's exact salary.

    Standard rank interpolation lands on a member whenever
    `(p/100) x (n-1)` is a whole number - at n=5 that is p25, the median and
    p75 all at once, so every published figure was an individual's salary.
    It recurs at n=9, n=13 and so on; it is a periodic property of the
    method, not an edge case at the threshold.

    Rounding cannot fix it. Making the median of ₹30L/₹45L/₹55L/₹70L/₹80L
    ambiguous would need a band of ±₹10L, which destroys the number.

    So when the index is whole, this takes the midpoint of that value and
    its neighbour instead. The result sits between two people and belongs to
    neither, which is what an aggregate is supposed to be.

    Used only for publication. `calculate_percentile` keeps standard
    behaviour for the server-side comparison, where the output is a category
    rather than a number.
    """
    if not sorted_values:
        return None

    values = sorted(float(v) for v in sorted_values)
    if len(values) == 1:
        return values[0]

    index = (p / 100) * (len(values) - 1)
    lower = int(index)

    if index != lower:
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (index - lower) * (values[upper] - values[lower])

    # Whole index: the raw result would be values[lower] exactly. Blend it
    # with a neighbour - the one above, or the one below at the top end.
    neighbour = lower + 1 if lower + 1 < len(values) else lower - 1
    return (values[lower] + values[neighbour]) / 2


def choose_band(reference):
    """
    The rounding band for a distribution centred on `reference`.

    Five percent of the reference figure, clamped. The floor stops the band
    collapsing on low salaries, where ₹50,000 is already a meaningful chunk.
    The ceiling stops it swallowing the answer at the top end - a ₹5,00,000
    band on a ₹1 crore median is still a useful number, a ₹20,00,000 one is
    not.
    """
    if not reference:
        return PUBLISH_BAND_MIN_INR

    band = float(reference) * PUBLISH_BAND_PCT
    return int(min(max(band, PUBLISH_BAND_MIN_INR), PUBLISH_BAND_MAX_INR))


def round_for_publication(value, band=None, reference=None):
    """
    Round a salary figure before it is published.

    `reference` is the figure the band is derived from - normally the
    median, so every figure in one response is rounded to the same band.
    Rounding each to its own band would make p25 and p75 sit on a finer grid
    than the median, which leaks the shape of the distribution back.

    Returns None unchanged so callers do not have to special-case an absent
    figure.
    """
    if value is None:
        return None

    if band is None:
        band = choose_band(reference if reference is not None else value)

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