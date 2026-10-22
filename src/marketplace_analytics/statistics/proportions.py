"""Confidence intervals and tests for proportions.

Implemented directly (rather than only calling statsmodels) so the formulas are visible;
the unit tests cross-check every function against statsmodels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats


def _z(alpha: float) -> float:
    return float(stats.norm.ppf(1 - alpha / 2))


def wilson_ci(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal (Wald) interval because it stays inside [0, 1] and keeps
    close to nominal coverage for small n or proportions near 0 or 1.
    """
    if n <= 0:
        return (math.nan, math.nan)
    z = _z(alpha)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe_diff_ci(
    x1: int, n1: int, x2: int, n2: int, alpha: float = 0.05
) -> tuple[float, float]:
    """Newcombe hybrid-score CI for p1 - p2, built from the two Wilson intervals."""
    p1, p2 = x1 / n1, x2 / n2
    l1, u1 = wilson_ci(x1, n1, alpha)
    l2, u2 = wilson_ci(x2, n2, alpha)
    d = p1 - p2
    lower = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (lower, upper)


@dataclass(frozen=True)
class TwoProportionResult:
    p1: float
    p2: float
    n1: int
    n2: int
    difference: float  # p1 - p2, absolute (proportion points)
    relative_difference: float  # (p1 - p2) / p2
    ci_low: float
    ci_high: float
    z: float
    p_value: float


def two_proportion_test(
    x1: int, n1: int, x2: int, n2: int, alpha: float = 0.05
) -> TwoProportionResult:
    """Two-sided pooled z-test for H0: p1 = p2, with a Newcombe CI for the difference.

    The test uses the pooled standard error (the null assumes equal proportions); the
    interval uses Newcombe's method, which does not.
    """
    if min(n1, n2) <= 0:
        raise ValueError("Both groups need at least one observation")
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se if se > 0 else 0.0
    p_value = float(2 * stats.norm.sf(abs(z)))
    low, high = newcombe_diff_ci(x1, n1, x2, n2, alpha)
    rel = (p1 - p2) / p2 if p2 > 0 else math.nan
    return TwoProportionResult(p1, p2, n1, n2, p1 - p2, rel, low, high, z, p_value)
