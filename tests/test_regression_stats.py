"""Statistical helpers checked against closed-form results and simulated truth."""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from marketplace_analytics.reporting.regression import cmh_test, late_or_by_timing
from marketplace_analytics.statistics.regression import (
    average_marginal_effect,
    average_predictions,
    fit_logit,
    roc_auc,
    tidy,
    vif_table,
)


def _simulated(n=20_000, seed=1):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "x": rng.normal(size=n),
            "late": rng.binomial(1, 0.2, size=n),
            "g": rng.choice(["a", "b", "c"], size=n),
            "cluster": rng.integers(0, 200, size=n),
        }
    )
    eta = -2 + 0.5 * df["x"] + 1.0 * df["late"] + df["g"].map({"a": 0, "b": 0.4, "c": -0.4})
    df["y"] = rng.binomial(1, 1 / (1 + np.exp(-eta)))
    return df


def test_roc_auc_matches_pairwise_definition_with_ties():
    y = np.array([0, 0, 1, 1, 0, 1])
    p = np.array([0.1, 0.4, 0.4, 0.8, 0.6, 0.3])
    pos, neg = p[y == 1], p[y == 0]
    pairs = [1.0 if a > b else 0.5 if a == b else 0.0 for a, b in itertools.product(pos, neg)]
    assert roc_auc(y, p) == pytest.approx(np.mean(pairs))


def test_fit_logit_recovers_simulated_coefficients():
    fit = fit_logit("y ~ x + late + C(g, Treatment('a'))", _simulated(), cluster="cluster")
    t = tidy(fit).set_index("term")
    assert t.loc["x", "coef"] == pytest.approx(0.5, abs=0.08)
    assert t.loc["late", "coef"] == pytest.approx(1.0, abs=0.1)
    assert t.loc["late", "odds_ratio"] == pytest.approx(np.exp(t.loc["late", "coef"]))
    assert t.loc["late", "or_ci_low"] < t.loc["late", "odds_ratio"] < t.loc["late", "or_ci_high"]


def test_fit_logit_refuses_missing_values():
    df = _simulated(500)
    df.loc[0, "x"] = np.nan
    with pytest.raises(Exception, match=r"(?i)nan|missing"):
        fit_logit("y ~ x", df)


def test_ame_equals_raw_difference_in_a_saturated_model():
    df = _simulated(5000)
    fit = fit_logit("y ~ late", df)
    ame = average_marginal_effect(fit, "late", 1, 0, n_draws=200, seed=0)
    raw = df.loc[df.late == 1, "y"].mean() - df.loc[df.late == 0, "y"].mean()
    assert ame["ame"] == pytest.approx(raw, abs=1e-9)
    assert ame["ame_ci_low"] < ame["ame"] < ame["ame_ci_high"]


def test_ame_accepts_counterfactual_shift():
    df = _simulated(5000)
    fit = fit_logit("y ~ x", df)
    up = average_marginal_effect(fit, "x", lambda v: v + 1, lambda v: v, n_draws=100)
    assert up["ame"] > 0  # true coefficient on x is positive


def test_average_predictions_equal_group_means_in_saturated_model():
    df = _simulated(5000)
    fit = fit_logit("y ~ C(g, Treatment('a'))", df)
    pred = average_predictions(fit, "g", ["a", "b", "c"], n_draws=200).set_index("level")
    means = df.groupby("g")["y"].mean()
    for g in "abc":
        assert pred.loc[g, "probability"] == pytest.approx(means[g], abs=1e-9)


def test_late_or_by_timing_matches_stratum_odds_ratios():
    rng = np.random.default_rng(3)
    n = 6000
    df = pd.DataFrame(
        {
            "late": rng.binomial(1, 0.3, n),
            "timing": rng.choice(["post", "pre", "same_day"], n),
        }
    )
    eta = -2 + df["late"] * df["timing"].map({"post": 0.7, "pre": 2.0, "same_day": 1.2})
    df["low_review"] = rng.binomial(1, 1 / (1 + np.exp(-eta)))
    fit = fit_logit("low_review ~ late * C(timing, Treatment('post'))", df)
    got = late_or_by_timing(fit, "late", "timing").set_index("timing")["odds_ratio"]
    for level, g in df.groupby("timing"):
        t = pd.crosstab(g["late"], g["low_review"])
        empirical = (t.loc[1, 1] * t.loc[0, 0]) / (t.loc[1, 0] * t.loc[0, 1])
        assert got[level] == pytest.approx(empirical, rel=1e-6)


def test_cmh_pooled_or_matches_mantel_haenszel_formula():
    df = _simulated(8000).rename(columns={"y": "low_review"})
    res = cmh_test(df, "g")
    num = den = 0.0
    for _, g in df.groupby("g"):
        a = ((g.late == 1) & (g.low_review == 1)).sum()
        b = ((g.late == 1) & (g.low_review == 0)).sum()
        c = ((g.late == 0) & (g.low_review == 1)).sum()
        d = ((g.late == 0) & (g.low_review == 0)).sum()
        num += a * d / len(g)
        den += b * c / len(g)
    assert res["pooled_or"] == pytest.approx(num / den)
    assert res["strata_used"] == 3


def test_vif_detects_collinearity():
    df = _simulated(3000)
    df["x_copy"] = df["x"] * 2 + np.random.default_rng(0).normal(scale=0.05, size=len(df))
    vif = vif_table(fit_logit("y ~ x + x_copy + late", df)).set_index("term")["vif"]
    assert vif["x"] > 50 and vif["x_copy"] > 50
    assert vif["late"] < 1.1


def test_delta_method_ame_se_equals_wald_se_in_saturated_model():
    df = _simulated(8000)
    fit = fit_logit("y ~ late", df)  # model-based SEs
    ame = average_marginal_effect(fit, "late", 1, 0, n_draws=100, seed=0)
    g1, g0 = df.loc[df.late == 1, "y"], df.loc[df.late == 0, "y"]
    p1, p0 = g1.mean(), g0.mean()
    wald = np.sqrt(p1 * (1 - p1) / len(g1) + p0 * (1 - p0) / len(g0))
    assert ame["ame_se_delta"] == pytest.approx(wald, rel=1e-6)
    assert ame["ame_delta_ci_low"] < ame["ame"] < ame["ame_delta_ci_high"]
