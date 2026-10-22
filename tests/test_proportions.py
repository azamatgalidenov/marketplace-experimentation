"""Cross-check the hand-written proportion statistics against statsmodels."""

from __future__ import annotations

import math

import pytest
from statsmodels.stats.proportion import (
    confint_proportions_2indep,
    proportion_confint,
    proportions_ztest,
)

from marketplace_analytics.statistics.proportions import (
    newcombe_diff_ci,
    two_proportion_test,
    wilson_ci,
)

CASES = [(0, 10), (1, 10), (37, 120), (500, 1000), (9, 9), (3982, 89182)]


@pytest.mark.parametrize(("x", "n"), CASES)
def test_wilson_matches_statsmodels(x, n):
    expected = proportion_confint(x, n, alpha=0.05, method="wilson")
    assert wilson_ci(x, n) == pytest.approx(expected, abs=1e-12)


def test_wilson_stays_in_unit_interval_and_handles_empty():
    low, high = wilson_ci(0, 5)
    assert low == 0 and 0 < high < 1
    assert all(math.isnan(v) for v in wilson_ci(0, 0))


@pytest.mark.parametrize(
    ("x1", "n1", "x2", "n2"), [(30, 100, 20, 100), (3981, 6378, 8247, 89182), (0, 50, 3, 60)]
)
def test_newcombe_matches_statsmodels(x1, n1, x2, n2):
    expected = confint_proportions_2indep(x1, n1, x2, n2, method="newcomb", compare="diff")
    assert newcombe_diff_ci(x1, n1, x2, n2) == pytest.approx(expected, abs=1e-10)


def test_two_proportion_z_matches_statsmodels_pooled_test():
    res = two_proportion_test(120, 1000, 100, 1000)
    z, p = proportions_ztest([120, 100], [1000, 1000], alternative="two-sided")
    assert res.z == pytest.approx(z)
    assert res.p_value == pytest.approx(p)
    assert res.difference == pytest.approx(0.02)
    assert res.relative_difference == pytest.approx(0.2)
    assert res.ci_low < res.difference < res.ci_high


def test_two_proportion_test_rejects_empty_groups():
    with pytest.raises(ValueError):
        two_proportion_test(0, 0, 1, 10)
