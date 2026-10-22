"""Validate the SIMULATED experiment machinery by repeated simulation.

Each replication runs the real simulator (fresh users, fresh hash salt) and the real
analysis function on observed outcomes only. The true parameters are used afterwards,
and only here, to score the results:

* false-positive rate under A/A and null scenarios (should be ~alpha),
* power under a positive scenario (should match the analytic power),
* 95% CI coverage of the true effect (should be ~95%),
* sample-ratio-mismatch detection with and without an injected logging loss.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import stats

from marketplace_analytics.experiments.analysis import proportion_effect, srm_check
from marketplace_analytics.experiments.design import ExperimentDesign, Population, Scenario
from marketplace_analytics.experiments.power import power_for_effect
from marketplace_analytics.experiments.regression import FORMULAS, model_frame
from marketplace_analytics.experiments.simulate import simulate_experiment
from marketplace_analytics.statistics.proportions import wilson_ci
from marketplace_analytics.statistics.regression import average_marginal_effect, fit_logit, tidy

logger = logging.getLogger(__name__)


def srm_detection_power(
    n_users: int, treatment_share: float, logging_loss: float, srm_alpha: float
) -> float:
    """Probability that the chi-square SRM test flags a given treatment logging loss.

    After losing ``logging_loss`` of treatment users the observed treatment share is q;
    the 1-df chi-square statistic is noncentral with lambda = N (q - s)^2 / (s (1 - s)).
    """
    s = treatment_share
    n_obs = n_users * (1 - s * logging_loss)
    q = s * (1 - logging_loss) / (1 - s * logging_loss)
    lam = n_obs * (q - s) ** 2 / (s * (1 - s))
    crit = stats.chi2.ppf(1 - srm_alpha, df=1)
    return float(stats.ncx2.sf(crit, df=1, nc=lam)) if lam > 0 else srm_alpha


def observed_user_table(sim) -> pd.DataFrame:
    """User-level analysis table from simulator output (Python twin of the SQL fact)."""
    first = sim.assignment_events.sort_values("exposed_at").drop_duplicates("user_id")
    return first[["user_id", "variant"]].merge(sim.outcomes, on="user_id", how="left")


def replicate(
    design: ExperimentDesign,
    population: Population,
    scenario: Scenario,
    replications: int,
    seed: int,
    n_users: int | None = None,
    logging_loss: float = 0.0,
) -> pd.DataFrame:
    """Simulate and analyse ``replications`` independent experiments.

    ``logging_loss`` drops that share of treatment users from the analysis table,
    mimicking a tracking bug, to test whether the SRM check catches it.
    """
    rng = np.random.default_rng(seed)
    true_effect = 0.0 if scenario.identical_arms else scenario.conversion_abs
    rows = []
    for r in range(replications):
        sim = simulate_experiment(
            design,
            population,
            scenario,
            seed=int(rng.integers(2**31)),
            n_users=n_users,
            user_prefix=f"r{r}-",
            salt_suffix=f":rep{r}",
        )
        df = observed_user_table(sim)
        if logging_loss:
            drop = (df["variant"] == "treatment") & (rng.random(len(df)) < logging_loss)
            df = df.loc[~drop]
        eff = proportion_effect(df, "purchased", design.alpha)  # observed outcomes only
        srm = srm_check(df, design.treatment_share, design.srm_alpha)
        rows.append(
            {
                "replication": r,
                "abs_diff": eff["abs_diff"],
                "ci_low": eff["abs_ci_low"],
                "ci_high": eff["abs_ci_high"],
                "p_value": eff["p_value"],
                "rejected": eff["p_value"] < design.alpha,
                "covered": eff["abs_ci_low"] <= true_effect <= eff["abs_ci_high"],
                "srm_p_value": srm["p_value"],
                "srm_detected": srm["srm_detected"],
                "true_effect": true_effect,
            }
        )
    return pd.DataFrame(rows)


def summarise(
    reps: pd.DataFrame, label: str, check: str, expected: float, design: ExperimentDesign
) -> dict:
    column = {"rejection": "rejected", "coverage": "covered", "srm": "srm_detected"}[check]
    k, n = int(reps[column].sum()), len(reps)
    lo, hi = wilson_ci(k, n, alpha=0.01)  # 99% interval: tolerance for simulation noise
    return {
        "check": label,
        "metric": check,
        "replications": n,
        "observed_rate": k / n,
        "ci99_low": lo,
        "ci99_high": hi,
        "expected_rate": expected,
        "consistent": bool(lo <= expected <= hi),
        "mean_estimate": float(reps["abs_diff"].mean()),
        "true_effect": float(reps["true_effect"].iloc[0]),
    }


def run_validation(
    design: ExperimentDesign,
    population: Population,
    scenarios: dict[str, Scenario],
    replications: int,
    seed: int,
    logging_losses: list[float],
    n_users: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = n_users or design.planned_users
    n_arm = n * min(design.treatment_share, 1 - design.treatment_share)
    baseline = population.expected_baseline_conversion()
    all_reps, summary = [], []
    plan = [
        ("aa", "A/A", 0.0),
        ("null_effect", "Null effect", 0.0),
        ("positive", "Positive effect", None),
        ("small_effect", "Small effect (below MDE)", None),
    ]
    for i, (name, label, _) in enumerate(plan):
        scen = scenarios[name]
        logger.info("Validation: %s x %d replications", label, replications)
        reps = replicate(design, population, scen, replications, seed + i, n, logging_loss=0.0)
        reps["scenario"] = name
        all_reps.append(reps)
        effect = 0.0 if scen.identical_arms else scen.conversion_abs
        expected = (
            design.alpha if effect == 0 else power_for_effect(baseline, effect, n_arm, design.alpha)
        )
        summary.append(summarise(reps, f"{label}: rejection rate", "rejection", expected, design))
        summary.append(summarise(reps, f"{label}: 95% CI coverage", "coverage", 0.95, design))
        if name == "aa":
            summary.append(
                summarise(reps, "A/A: SRM false alarms", "srm", design.srm_alpha, design)
            )
    for j, loss in enumerate(logging_losses):
        logger.info("Validation: SRM with %.0f%% treatment logging loss", loss * 100)
        lossy = replicate(
            design,
            population,
            scenarios["aa"],
            max(replications // 5, 50),
            seed + 99 + j,
            n,
            logging_loss=loss,
        )
        lossy["scenario"] = f"aa_logging_loss_{loss:.0%}"
        all_reps.append(lossy)
        expected = srm_detection_power(n, design.treatment_share, loss, design.srm_alpha)
        summary.append(
            summarise(lossy, f"SRM detection, {loss:.0%} treatment loss", "srm", expected, design)
        )
    return pd.DataFrame(summary), pd.concat(all_reps, ignore_index=True)


def replicate_adjusted(
    design: ExperimentDesign,
    population: Population,
    scenario: Scenario,
    replications: int,
    seed: int,
    n_users: int | None = None,
    n_draws: int = 200,
) -> pd.DataFrame:
    """Repeated simulation of the covariate-adjusted logit (treatment AME).

    Scores type I error / power, CI coverage of the true effect and the CI width relative
    to the unadjusted Newcombe interval on the same data.
    """
    rng = np.random.default_rng(seed)
    true_effect = 0.0 if scenario.identical_arms else scenario.conversion_abs
    rows = []
    for r in range(replications):
        sim = simulate_experiment(
            design,
            population,
            scenario,
            seed=int(rng.integers(2**31)),
            n_users=n_users,
            user_prefix=f"r{r}-",
            salt_suffix=f":adj{r}",
        )
        users = observed_user_table(sim).merge(
            sim.users[["user_id", "device", "customer_type"]], on="user_id"
        )
        frame = model_frame(users)
        fit = fit_logit(FORMULAS["adjusted"], frame, robust=True)
        ame = average_marginal_effect(fit, "treatment", 1, 0, n_draws=n_draws, seed=r)
        # Same interval method (delta) for both models, so widths are comparable.
        unadj_fit = fit_logit(FORMULAS["unadjusted"], frame, robust=True)
        unadj = average_marginal_effect(unadj_fit, "treatment", 1, 0, n_draws=n_draws, seed=r)
        lo, hi = ame["ame_delta_ci_low"], ame["ame_delta_ci_high"]
        rows.append(
            {
                "replication": r,
                "scenario": scenario.name,
                "true_effect": true_effect,
                "adjusted_ame": ame["ame"],
                "adjusted_ci_width": hi - lo,
                "adjusted_covered": lo <= true_effect <= hi,
                "adjusted_rejected": tidy(fit).set_index("term").loc["treatment", "p_value"]
                < design.alpha,
                "unadjusted_diff": unadj["ame"],
                "unadjusted_ci_width": unadj["ame_delta_ci_high"] - unadj["ame_delta_ci_low"],
            }
        )
    return pd.DataFrame(rows)


def summarise_adjusted(reps: pd.DataFrame, design: ExperimentDesign, expected_rejection: float):
    """Coverage, rejection rate (99% tolerance) and precision gain of the adjusted model."""
    n = len(reps)
    out = []
    for label, column, expected in [
        ("rejection rate", "adjusted_rejected", expected_rejection),
        ("95% CI coverage", "adjusted_covered", 0.95),
    ]:
        k = int(reps[column].sum())
        lo, hi = wilson_ci(k, n, alpha=0.01)
        out.append(
            {
                "scenario": reps["scenario"].iloc[0],
                "check": f"Adjusted logit: {label}",
                "replications": n,
                "observed_rate": k / n,
                "ci99_low": lo,
                "ci99_high": hi,
                "expected_rate": expected,
                "consistent": bool(lo <= expected <= hi),
            }
        )
    ratio = reps["adjusted_ci_width"] / reps["unadjusted_ci_width"]
    out.append(
        {
            "scenario": reps["scenario"].iloc[0],
            "check": "Adjusted / unadjusted CI width (mean)",
            "replications": n,
            "observed_rate": float(ratio.mean()),
            "ci99_low": float(ratio.quantile(0.005)),
            "ci99_high": float(ratio.quantile(0.995)),
            "expected_rate": np.nan,
            "consistent": None,
        }
    )
    out.append(
        {
            "scenario": reps["scenario"].iloc[0],
            "check": "Mean adjusted AME minus true effect (bias)",
            "replications": n,
            "observed_rate": float((reps["adjusted_ame"] - reps["true_effect"]).mean()),
            "ci99_low": np.nan,
            "ci99_high": np.nan,
            "expected_rate": 0.0,
            "consistent": None,
        }
    )
    return out
