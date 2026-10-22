"""Analysis of a (SIMULATED) A/B test from observed user-level data only.

Every function here takes the analysis dataset (one row per assigned user) and the
pre-registered design. None of them can see the simulation's true parameters.

Expected columns: variant, purchased, net_order_value, checkout_error, cancelled_order,
order_value (purchasers only), checkout_seconds (purchasers only), device, customer_type.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from marketplace_analytics.experiments.design import SEGMENTS, ExperimentDesign
from marketplace_analytics.experiments.power import mde_for_n
from marketplace_analytics.statistics.proportions import two_proportion_test

Z95 = stats.norm.ppf(0.975)


def proportion_effect(df: pd.DataFrame, column: str, alpha: float = 0.05) -> dict:
    """Treatment vs control for a binary user-level metric.

    Pooled two-proportion z-test (H0: equal rates) and Newcombe hybrid-score CI for the
    absolute difference; relative-lift CI from the log risk ratio (delta method).
    """
    t = df.loc[df["variant"] == "treatment", column].astype(bool)
    c = df.loc[df["variant"] == "control", column].astype(bool)
    x1, n1, x2, n2 = int(t.sum()), len(t), int(c.sum()), len(c)
    res = two_proportion_test(x1, n1, x2, n2, alpha=alpha)
    rel_lo = rel_hi = math.nan
    if x1 > 0 and x2 > 0:
        se_log = math.sqrt((1 - res.p1) / x1 + (1 - res.p2) / x2)
        log_rr = math.log(res.p1 / res.p2)
        z = stats.norm.ppf(1 - alpha / 2)
        rel_lo, rel_hi = math.exp(log_rr - z * se_log) - 1, math.exp(log_rr + z * se_log) - 1
    return {
        "metric_type": "proportion",
        "n_treatment": n1,
        "n_control": n2,
        "successes_treatment": x1,
        "successes_control": x2,
        "value_treatment": res.p1,
        "value_control": res.p2,
        "abs_diff": res.difference,
        "abs_ci_low": res.ci_low,
        "abs_ci_high": res.ci_high,
        "rel_diff": res.relative_difference,
        "rel_ci_low": rel_lo,
        "rel_ci_high": rel_hi,
        "p_value": res.p_value,
        "test": "two-proportion z-test (pooled); Newcombe CI",
    }


def mean_effect(df: pd.DataFrame, column: str, alpha: float = 0.05, log: bool = False) -> dict:
    """Treatment vs control for a continuous metric (Welch t-test, unequal variances).

    With ``log=True`` the comparison is on log values and the relative difference is the
    ratio of geometric means minus 1 (for skewed, strictly positive metrics).
    The relative CI for raw means uses the delta method for a ratio of two means.
    """
    t = df.loc[df["variant"] == "treatment", column].dropna().astype(float)
    c = df.loc[df["variant"] == "control", column].dropna().astype(float)
    if log:
        t, c = np.log(t), np.log(c)
    n1, n2 = len(t), len(c)
    m1, m2 = t.mean(), c.mean()
    v1, v2 = t.var(ddof=1), c.var(ddof=1)
    se = math.sqrt(v1 / n1 + v2 / n2)
    dof = se**4 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    tcrit = stats.t.ppf(1 - alpha / 2, dof)
    test = stats.ttest_ind(t, c, equal_var=False)
    diff = m1 - m2
    lo, hi = diff - tcrit * se, diff + tcrit * se
    if log:
        value_t, value_c = math.exp(m1), math.exp(m2)
        rel, rel_lo, rel_hi = math.exp(diff) - 1, math.exp(lo) - 1, math.exp(hi) - 1
        abs_diff, abs_lo, abs_hi = value_t - value_c, math.nan, math.nan
    else:
        value_t, value_c = m1, m2
        rel = m1 / m2 - 1
        se_rel = (m1 / m2) * math.sqrt(v1 / (n1 * m1**2) + v2 / (n2 * m2**2))
        rel_lo, rel_hi = rel - Z95 * se_rel, rel + Z95 * se_rel
        abs_diff, abs_lo, abs_hi = diff, lo, hi
    return {
        "metric_type": "geometric mean" if log else "mean",
        "n_treatment": n1,
        "n_control": n2,
        "successes_treatment": math.nan,
        "successes_control": math.nan,
        "value_treatment": value_t,
        "value_control": value_c,
        "abs_diff": abs_diff,
        "abs_ci_low": abs_lo,
        "abs_ci_high": abs_hi,
        "rel_diff": rel,
        "rel_ci_low": rel_lo,
        "rel_ci_high": rel_hi,
        "p_value": float(test.pvalue),
        "test": "Welch t-test" + (" on log values" if log else ""),
    }


def srm_check(df: pd.DataFrame, treatment_share: float, srm_alpha: float) -> dict:
    """Chi-square goodness-of-fit test of assigned counts against the planned split."""
    n_t = int((df["variant"] == "treatment").sum())
    n_c = int((df["variant"] == "control").sum())
    n = n_t + n_c
    chi = stats.chisquare([n_t, n_c], f_exp=[n * treatment_share, n * (1 - treatment_share)])
    return {
        "n_treatment": n_t,
        "n_control": n_c,
        "observed_treatment_share": n_t / n if n else math.nan,
        "expected_treatment_share": treatment_share,
        "chi2": float(chi.statistic),
        "p_value": float(chi.pvalue),
        "srm_detected": bool(chi.pvalue < srm_alpha),
    }


# name, role, column, estimator, harmful direction, margin key, margin scale
METRICS = [
    ("purchase_completion", "primary", "purchased", "proportion", None, None, None),
    (
        "net_order_value_per_user",
        "guardrail",
        "net_order_value",
        "mean",
        "decrease",
        "revenue_per_user_rel",
        "relative",
    ),
    (
        "checkout_error_rate",
        "guardrail",
        "checkout_error",
        "proportion",
        "increase",
        "checkout_error_rate_abs",
        "absolute",
    ),
    (
        "cancellation_rate",
        "guardrail",
        "cancelled_order",
        "proportion",
        "increase",
        "cancellation_rate_abs",
        "absolute",
    ),
    ("aov_purchasers", "secondary", "order_value", "mean", None, None, None),
    ("checkout_seconds_purchasers", "secondary", "checkout_seconds", "log_mean", None, None, None),
]


def guardrail_status(effect: dict, harmful: str, margin: float, scale: str) -> str:
    """green: deterioration beyond the margin ruled out (non-inferiority shown);
    red: statistically significant deterioration not ruled out to be within the margin;
    amber: neither (cannot rule out a deterioration larger than the margin)."""
    lo, hi = (
        (effect["rel_ci_low"], effect["rel_ci_high"])
        if scale == "relative"
        else (effect["abs_ci_low"], effect["abs_ci_high"])
    )
    if harmful == "decrease":
        if lo >= -margin:
            return "green"
        return "red" if hi < 0 else "amber"
    if hi <= margin:
        return "green"
    return "red" if lo > 0 else "amber"


def analyze_metrics(df: pd.DataFrame, design: ExperimentDesign) -> pd.DataFrame:
    rows = []
    for name, role, column, estimator, harmful, margin_key, scale in METRICS:
        if estimator == "proportion":
            effect = proportion_effect(df, column, design.alpha)
        else:
            effect = mean_effect(df, column, design.alpha, log=estimator == "log_mean")
        row = {"metric": name, "role": role, **effect}
        if role == "guardrail":
            margin = design.guardrail_margins[margin_key]
            row |= {
                "harmful_direction": harmful,
                "margin": margin,
                "margin_scale": scale,
                "guardrail_status": guardrail_status(effect, harmful, margin, scale),
            }
        if role == "secondary":
            row["note"] = "Conditional on purchase (post-treatment subset): descriptive only."
        if role == "primary":
            row["significant"] = effect["p_value"] < design.alpha
        rows.append(row)
    return pd.DataFrame(rows)


def segment_analysis(df: pd.DataFrame, design: ExperimentDesign) -> pd.DataFrame:
    """Primary metric within pre-registered segments (exploratory).

    p-values are Benjamini-Hochberg adjusted across all segment comparisons. Segments
    with fewer than ``segment_min_users_per_arm`` users in either arm are flagged.
    """
    rows = []
    for segment in SEGMENTS:
        for level, sub in df.groupby(segment):
            effect = proportion_effect(sub, "purchased", design.alpha)
            n_arm = min(effect["n_treatment"], effect["n_control"])
            rows.append(
                {
                    "segment": segment,
                    "level": level,
                    **effect,
                    "segment_mde_abs": mde_for_n(
                        effect["value_control"], n_arm, design.alpha, design.power
                    ),
                    "small_sample": n_arm < design.segment_min_users_per_arm,
                }
            )
    out = pd.DataFrame(rows)
    out["p_value_bh"] = multipletests(out["p_value"], method="fdr_bh")[1]
    out["significant_after_bh"] = out["p_value_bh"] < design.alpha
    return out


@dataclass
class Decision:
    decision: str  # LAUNCH | REJECT | CONTINUE TESTING | INVALID | A/A PASS | A/A FAIL
    reasons: list[str] = field(default_factory=list)


def decide(
    metrics: pd.DataFrame, srm: dict, design: ExperimentDesign, aa_test: bool = False
) -> Decision:
    """Apply the pre-registered decision rules (docs/experiment_plan.md, section 6)."""
    primary = metrics.set_index("metric").loc["purchase_completion"]
    guard = metrics[metrics["role"] == "guardrail"]
    lo, hi, est = primary["abs_ci_low"], primary["abs_ci_high"], primary["abs_diff"]
    thr = design.practical_threshold_abs

    if srm["srm_detected"]:
        return Decision(
            "INVALID",
            [
                f"Sample-ratio mismatch (p={srm['p_value']:.2g}); "
                "assignment or logging is broken - do not interpret."
            ],
        )
    if aa_test:
        ok = primary["p_value"] >= design.alpha
        return Decision(
            "A/A PASS" if ok else "A/A FAIL",
            [
                f"Primary difference {est * 100:+.2f} pp, p={primary['p_value']:.3f}; "
                "an A/A test is expected to be non-significant 95% of the time."
            ],
        )

    red = guard[guard["guardrail_status"] == "red"]["metric"].tolist()
    amber = guard[guard["guardrail_status"] == "amber"]["metric"].tolist()
    ci = f"{est * 100:+.2f} pp (95% CI {lo * 100:+.2f} to {hi * 100:+.2f})"

    if red:
        return Decision("REJECT", [f"Guardrail breached: {', '.join(red)}.", f"Primary {ci}."])
    if hi < 0:
        return Decision("REJECT", [f"Primary metric significantly worse: {ci}."])
    if lo > 0 and est >= thr:
        if amber:
            return Decision(
                "CONTINUE TESTING",
                [
                    f"Primary improved: {ci}.",
                    "Guardrail not cleared (cannot rule out harm beyond margin): "
                    f"{', '.join(amber)}.",
                ],
            )
        return Decision(
            "LAUNCH",
            [
                f"Primary improved: {ci}; estimate >= {thr * 100:.1f} pp.",
                "All guardrails within margins.",
            ],
        )
    if hi < thr:
        return Decision(
            "REJECT",
            [
                f"Primary {ci}: effects of {thr * 100:.1f} pp or more are ruled out, so any "
                "effect is too small to justify launch."
            ],
        )
    return Decision(
        "CONTINUE TESTING",
        [
            f"Inconclusive: {ci} is consistent with no effect and with a worthwhile lift "
            f"(>= {thr * 100:.1f} pp). Not evidence of no effect.",
            "Next step: a new, pre-registered test sized for the smallest lift still worth "
            "launching - not an extension of this one.",
        ]
        + ([f"Guardrails not cleared: {', '.join(amber)}."] if amber else []),
    )
