"""Logistic regression of the SIMULATED experiment: correctness against known truths."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from marketplace_analytics.config import load_settings
from marketplace_analytics.experiments.analysis import proportion_effect
from marketplace_analytics.experiments.design import load_experiment
from marketplace_analytics.experiments.regression import (
    FORMULAS,
    device_effects,
    fit_models,
    interaction_test,
    mediator_bias_demo,
    model_frame,
    treatment_effects,
)
from marketplace_analytics.experiments.simulate import simulate_experiment
from marketplace_analytics.experiments.validation import (
    observed_user_table,
    replicate_adjusted,
    summarise_adjusted,
)


@pytest.fixture(scope="module")
def experiment():
    design, population, scenarios = load_experiment(load_settings().section("experiment"))
    return design, population, {s.name: s for s in scenarios}


def _users(experiment, scenario, n, seed):
    design, population, scenarios = experiment
    sim = simulate_experiment(design, population, scenarios[scenario], seed, n_users=n)
    return observed_user_table(sim).merge(sim.users[["user_id", "device", "customer_type"]])


@pytest.fixture(scope="module")
def positive(experiment):
    users = _users(experiment, "positive", 21_000, 5)
    return users, fit_models(model_frame(users))


def test_model_frame_rejects_missing_and_codes_treatment():
    df = pd.DataFrame(
        {
            "user_id": ["a", "b"],
            "variant": ["treatment", "control"],
            "device": ["desktop"] * 2,
            "customer_type": ["new"] * 2,
            "purchased": [True, False],
        }
    )
    frame = model_frame(df)
    assert list(frame["treatment"]) == [1, 0] and list(frame["purchased"]) == [1, 0]
    with pytest.raises(ValueError):
        model_frame(df.assign(device=[None, "desktop"]))


def test_formulas_use_only_pre_treatment_covariates():
    post_treatment = ("checkout_error", "checkout_seconds", "order_value", "cancel", "net_order")
    for formula in FORMULAS.values():
        assert not any(term in formula for term in post_treatment)


def test_unadjusted_ame_reproduces_raw_difference(positive):
    users, fits = positive
    te = treatment_effects(fits, n_draws=200).set_index("model")
    raw = proportion_effect(users, "purchased")
    assert te.loc["unadjusted", "ame_abs"] == pytest.approx(raw["abs_diff"], abs=1e-9)
    # The odds ratio is a different quantity from the pp difference.
    p1, p0 = raw["value_treatment"], raw["value_control"]
    assert te.loc["unadjusted", "odds_ratio"] == pytest.approx((p1 / (1 - p1)) / (p0 / (1 - p0)))


def test_adjusted_estimate_is_close_and_not_wider(positive):
    _, fits = positive
    te = treatment_effects(fits, n_draws=500, seed=1).set_index("model")
    assert abs(te.loc["adjusted", "ame_abs"] - te.loc["unadjusted", "ame_abs"]) < 0.005
    assert te.loc["adjusted", "ame_ci_width"] <= te.loc["unadjusted", "ame_ci_width"] * 1.02


def test_interaction_test_and_device_effects(positive):
    users, fits = positive
    lr = interaction_test(fits)
    assert lr["df"] == 2 and 0 <= lr["p_value"] <= 1
    dev = device_effects(fits["interaction"], n_draws=200).set_index("device")
    assert set(dev.index) == set(users["device"])
    assert dev["users"].sum() == len(users)
    weighted = (dev["ame_abs"] * dev["users"]).sum() / dev["users"].sum()
    overall = treatment_effects({"i": fits["interaction"]}, n_draws=50)["ame_abs"].iloc[0]
    assert weighted == pytest.approx(overall, abs=1e-9)  # device AMEs average to the total


def test_interaction_detects_true_heterogeneity(experiment):
    """When the effect really differs by device, the LR test should find it."""
    design, population, scenarios = experiment
    users = _users(experiment, "aa", 30_000, 9)
    rng = np.random.default_rng(0)
    treated_web = (users["variant"] == "treatment") & (users["device"] == "mobile_web")
    flip = treated_web & ~users["purchased"] & (rng.random(len(users)) < 0.25)
    users.loc[flip, "purchased"] = True  # ~+12 pp effect for mobile_web only
    assert interaction_test(fit_models(model_frame(users)))["p_value"] < 0.001


def test_post_treatment_adjustment_recovers_only_the_direct_effect():
    demo = mediator_bias_demo(n=20_000, replications=60, seed=3).set_index("quantity")
    total = demo.loc["Estimate without mediator (correct)", "estimate"]
    biased = demo.loc["Estimate adjusting for errors (biased)", "estimate"]
    # Mean of 60 estimates: SE ~ 0.007 / sqrt(60) ~ 0.09 pp, so 0.5 pp is a ~5 SE bound.
    assert abs(total - 0.035) < 0.005
    assert abs(biased - 0.010) < 0.005
    assert total - biased > 0.015  # the mediator hides most of the effect


def test_adjusted_estimator_coverage_and_type_one_error(experiment):
    design, population, scenarios = experiment
    reps = replicate_adjusted(
        design, population, scenarios["aa"], 120, seed=7, n_users=4000, n_draws=100
    )
    summary = pd.DataFrame(summarise_adjusted(reps, design, design.alpha)).set_index("check")
    assert summary.loc["Adjusted logit: rejection rate", "consistent"]
    assert summary.loc["Adjusted logit: 95% CI coverage", "consistent"]
    assert summary.loc["Adjusted / unadjusted CI width (mean)", "observed_rate"] < 1.0
