"""SIMULATED experiment analysis: estimators, power, decisions and repeated-simulation checks.

Repeated-simulation tests compare an observed rate with its expectation using a 99.9%
binomial tolerance, so they fail only if the method is wrong (or ~1 run in 1000).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.proportion import proportions_ztest

from marketplace_analytics.config import load_settings
from marketplace_analytics.experiments.analysis import (
    analyze_metrics,
    decide,
    guardrail_status,
    mean_effect,
    proportion_effect,
    segment_analysis,
    srm_check,
)
from marketplace_analytics.experiments.design import load_experiment
from marketplace_analytics.experiments.power import (
    mde_for_n,
    power_for_effect,
    required_n_closed_form,
    required_n_per_arm,
)
from marketplace_analytics.experiments.simulate import simulate_experiment
from marketplace_analytics.experiments.validation import (
    observed_user_table,
    replicate,
    srm_detection_power,
)
from marketplace_analytics.statistics.proportions import wilson_ci


@pytest.fixture(scope="module")
def experiment():
    design, population, scenarios = load_experiment(load_settings().section("experiment"))
    return design, population, {s.name: s for s in scenarios}


def _users(n_t, x_t, n_c, x_c):
    return pd.DataFrame(
        {
            "variant": ["treatment"] * n_t + ["control"] * n_c,
            "purchased": [True] * x_t
            + [False] * (n_t - x_t)
            + [True] * x_c
            + [False] * (n_c - x_c),
        }
    )


def test_proportion_effect_matches_counts_and_statsmodels():
    df = _users(1000, 580, 1000, 550)
    eff = proportion_effect(df, "purchased")
    assert eff["n_treatment"] == 1000 and eff["n_control"] == 1000
    assert eff["abs_diff"] == pytest.approx(0.03)
    assert eff["rel_diff"] == pytest.approx(0.03 / 0.55)
    _, p = proportions_ztest([580, 550], [1000, 1000])
    assert eff["p_value"] == pytest.approx(p)
    assert eff["abs_ci_low"] < 0.03 < eff["abs_ci_high"]
    assert eff["rel_ci_low"] < eff["rel_diff"] < eff["rel_ci_high"]


def test_mean_effect_welch_and_log_scale():
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "variant": ["treatment"] * 4000 + ["control"] * 4000,
            "x": np.concatenate(
                [rng.lognormal(np.log(90), 0.5, 4000), rng.lognormal(np.log(100), 0.5, 4000)]
            ),
        }
    )
    raw = mean_effect(df, "x")
    log = mean_effect(df, "x", log=True)
    assert raw["abs_ci_low"] < raw["abs_diff"] < raw["abs_ci_high"] < 0
    assert log["rel_diff"] == pytest.approx(-0.10, abs=0.03)  # ratio of geometric means
    assert log["rel_ci_low"] < -0.10 < log["rel_ci_high"]


def test_srm_check_flags_imbalance_only_when_large():
    balanced = _users(10_050, 0, 9_950, 0)
    skewed = _users(10_500, 0, 9_500, 0)
    assert not srm_check(balanced, 0.5, 0.001)["srm_detected"]
    res = srm_check(skewed, 0.5, 0.001)
    assert res["srm_detected"] and res["p_value"] < 1e-10


@pytest.mark.parametrize(
    ("ci", "harmful", "expected"),
    [
        ((-0.001, 0.004), "increase", "green"),  # harm beyond 0.5 pp ruled out
        ((-0.002, 0.009), "increase", "amber"),  # cannot rule out harm > margin
        ((0.002, 0.012), "increase", "red"),  # significant increase, beyond margin possible
        ((-0.015, 0.01), "decrease", "green"),  # relative drop > 2% ruled out
        ((-0.04, -0.01), "decrease", "red"),
    ],
)
def test_guardrail_status(ci, harmful, expected):
    lo, hi = ci
    effect = {"abs_ci_low": lo, "abs_ci_high": hi, "rel_ci_low": lo, "rel_ci_high": hi}
    margin, scale = (0.005, "absolute") if harmful == "increase" else (0.02, "relative")
    assert guardrail_status(effect, harmful, margin, scale) == expected


def test_sample_size_methods_agree_and_scale_with_effect():
    n_sm = required_n_per_arm(0.55, 0.02)
    n_cf = required_n_closed_form(0.55, 0.02)
    assert abs(n_sm - n_cf) / n_cf < 0.02
    assert required_n_per_arm(0.55, 0.01) > 3.5 * n_sm  # ~1/effect^2


def test_mde_and_power_are_inverse():
    mde = mde_for_n(0.55, 10_000)
    assert power_for_effect(0.55, mde, 10_000) == pytest.approx(0.8, abs=1e-6)
    assert power_for_effect(0.55, 0.0, 10_000) == pytest.approx(0.05)


def _metrics(lo, est, hi, statuses=("green", "green", "green"), p=0.01):
    rows = [
        {
            "metric": "purchase_completion",
            "role": "primary",
            "abs_diff": est,
            "abs_ci_low": lo,
            "abs_ci_high": hi,
            "p_value": p,
        }
    ]
    for name, s in zip(["g1", "g2", "g3"], statuses, strict=True):
        rows.append({"metric": name, "role": "guardrail", "guardrail_status": s})
    return pd.DataFrame(rows)


NO_SRM = {"srm_detected": False, "p_value": 0.5}


@pytest.mark.parametrize(
    ("ci", "statuses", "expected"),
    [
        ((0.01, 0.025, 0.04), ("green",) * 3, "LAUNCH"),
        ((0.01, 0.025, 0.04), ("green", "amber", "green"), "CONTINUE TESTING"),
        ((0.01, 0.025, 0.04), ("green", "red", "green"), "REJECT"),
        ((-0.005, 0.008, 0.021), ("green",) * 3, "CONTINUE TESTING"),
        ((-0.012, -0.002, 0.008), ("green",) * 3, "REJECT"),  # effects >= 1 pp ruled out
        ((-0.04, -0.03, -0.02), ("green",) * 3, "REJECT"),
        ((0.001, 0.005, 0.009), ("green",) * 3, "REJECT"),  # significant but trivial
    ],
)
def test_decision_rules(experiment, ci, statuses, expected):
    design, *_ = experiment
    assert decide(_metrics(*ci, statuses), NO_SRM, design).decision == expected


def test_srm_overrides_every_other_result(experiment):
    design, *_ = experiment
    srm = {"srm_detected": True, "p_value": 1e-9}
    assert decide(_metrics(0.01, 0.03, 0.05), srm, design).decision == "INVALID"


def test_analysis_uses_observed_outcomes_not_parameters(experiment):
    """Same scenario parameters, shuffled outcomes -> the estimate follows the data."""
    design, population, scenarios = experiment
    sim = simulate_experiment(design, population, scenarios["positive"], 21, n_users=20_000)
    df = observed_user_table(sim).assign(net_order_value=0.0, cancelled_order=False)
    observed = proportion_effect(df, "purchased")["abs_diff"]
    shuffled = df.copy()
    shuffled["purchased"] = np.random.default_rng(0).permutation(df["purchased"].to_numpy())
    permuted = proportion_effect(shuffled, "purchased")["abs_diff"]
    # Observed is near the true +2.5 pp; permuting outcomes destroys it even though the
    # scenario parameters are unchanged.
    assert observed > 0.01
    assert abs(permuted) < 0.015
    t = (
        df[df.variant == "treatment"].purchased.mean()
        - df[df.variant == "control"].purchased.mean()
    )
    assert observed == pytest.approx(t)


def test_full_metric_and_segment_analysis_runs(experiment):
    design, population, scenarios = experiment
    sim = simulate_experiment(design, population, scenarios["guardrail_harm"], 8, n_users=6000)
    df = observed_user_table(sim).merge(sim.users[["user_id", "device", "customer_type"]])
    df["cancelled_order"] = df["purchased"] & df["order_cancelled"].fillna(False)
    df["net_order_value"] = np.where(
        df["purchased"] & ~df["order_cancelled"].fillna(False), df["order_value"], 0.0
    )
    metrics = analyze_metrics(df, design)
    assert set(metrics["role"]) == {"primary", "guardrail", "secondary"}
    assert metrics.loc[metrics.role == "guardrail", "guardrail_status"].notna().all()
    seg = segment_analysis(df, design)
    assert set(seg["segment"]) == {"device", "customer_type"}
    assert (seg["p_value_bh"] >= seg["p_value"] - 1e-12).all()  # BH never lowers p
    assert seg["small_sample"].any()  # 6,000 users split across segments is small


def _within(k, n, expected, alpha=0.001):
    lo, hi = wilson_ci(k, n, alpha=alpha)
    return lo <= expected <= hi


@pytest.mark.parametrize("scenario", ["aa", "null_effect"])
def test_false_positive_rate_is_nominal(experiment, scenario):
    design, population, scenarios = experiment
    reps = replicate(design, population, scenarios[scenario], 300, seed=101, n_users=4000)
    assert _within(int(reps["rejected"].sum()), len(reps), design.alpha)
    assert _within(int(reps["covered"].sum()), len(reps), 0.95)


def test_power_matches_analytic_expectation(experiment):
    design, population, scenarios = experiment
    n_users = 8000
    effect = 0.035  # gives power in a testable range at 8,000 users
    scen = scenarios["positive"].__class__(name="pos_test", description="", conversion_abs=effect)
    reps = replicate(design, population, scen, 300, seed=202, n_users=n_users)
    expected = power_for_effect(population.expected_baseline_conversion(), effect, n_users / 2)
    assert 0.5 < expected < 0.95
    assert _within(int(reps["rejected"].sum()), len(reps), expected)
    assert _within(int(reps["covered"].sum()), len(reps), 0.95)
    assert reps["abs_diff"].mean() == pytest.approx(effect, abs=0.005)  # unbiased


def test_srm_detection_matches_analytic_power(experiment):
    """SRM false alarms stay near srm_alpha; detection of a logging loss matches the
    noncentral chi-square power (a 3% loss is not reliably caught at this sample size)."""
    design, population, scenarios = experiment
    clean = replicate(design, population, scenarios["aa"], 100, seed=303, n_users=20_000)
    assert clean["srm_detected"].mean() <= 0.03
    for loss in (0.05, 0.10):
        lossy = replicate(
            design, population, scenarios["aa"], 100, seed=304, n_users=20_000, logging_loss=loss
        )
        expected = srm_detection_power(20_000, design.treatment_share, loss, design.srm_alpha)
        assert _within(int(lossy["srm_detected"].sum()), len(lossy), expected)
    assert srm_detection_power(20_000, 0.5, 0.10, 0.001) > 0.99
    assert srm_detection_power(20_000, 0.5, 0.0, 0.001) == pytest.approx(0.001)
