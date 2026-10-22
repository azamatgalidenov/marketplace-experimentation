"""Run the SIMULATED checkout experiment end to end and write its outputs.

simulate -> sim.* raw tables -> sql/sim -> sim_* quality checks -> analysis per scenario
-> SQL-vs-Python reconciliation -> power plan -> validation -> tables, charts, numbers.

Every output is SIMULATED and labelled as such.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from marketplace_analytics.config import Settings
from marketplace_analytics.data.warehouse import connect, run_quality_checks, run_sql_layer
from marketplace_analytics.experiments.analysis import (
    analyze_metrics,
    decide,
    segment_analysis,
    srm_check,
)
from marketplace_analytics.experiments.design import load_experiment
from marketplace_analytics.experiments.power import (
    guardrail_sensitivity,
    mde_for_n,
    power_curve,
    required_n_closed_form,
    required_n_per_arm,
)
from marketplace_analytics.experiments.simulate import simulate_experiment
from marketplace_analytics.experiments.validation import run_validation
from marketplace_analytics.reporting import style

logger = logging.getLogger(__name__)

SIM_NOTE = style.SIMULATED_SOURCE


class ExperimentReconciliationError(RuntimeError):
    """SQL and Python disagree on experiment metrics."""


@dataclass
class ExperimentResult:
    tables: dict[str, pd.DataFrame]
    figures: list[Path] = field(default_factory=list)
    key_numbers: dict = field(default_factory=dict)


def _write(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    con.register("_df", df)
    con.execute(f"CREATE OR REPLACE TABLE sim.{name} AS SELECT * FROM _df")
    con.unregister("_df")


def reconcile_sql_python(agg: pd.DataFrame, metrics: pd.DataFrame, scenario: str) -> list[str]:
    """Compare SQL variant summaries with the Python analysis inputs for one scenario."""
    sql = agg[agg["scenario"] == scenario].set_index("variant")
    m = metrics.set_index("metric")
    pairs = [
        ("purchase_completion", "purchase_completion_rate"),
        ("net_order_value_per_user", "net_order_value_per_user"),
        ("checkout_error_rate", "checkout_error_rate"),
        ("cancellation_rate", "cancellation_rate"),
        ("aov_purchasers", "aov_purchasers"),
        ("checkout_seconds_purchasers", "geomean_checkout_seconds"),
    ]
    problems = []
    for metric, column in pairs:
        for variant in ("treatment", "control"):
            py = m.loc[metric, f"value_{variant}"]
            sq = sql.loc[variant, column]
            if not np.isclose(py, sq, rtol=1e-9, atol=1e-12):
                problems.append(f"{scenario}/{variant}/{metric}: python={py} sql={sq}")
        py_n = m.loc["purchase_completion", "n_treatment"]
        if py_n != sql.loc["treatment", "assigned_users"]:
            problems.append(f"{scenario}: treatment denominator mismatch")
    return problems


def chart_primary(metrics: pd.DataFrame, decisions: pd.DataFrame, thr: float, path: Path) -> Path:
    d = metrics[metrics["metric"] == "purchase_completion"].merge(decisions, on="scenario")
    d = d.iloc[::-1].reset_index(drop=True)
    fig, ax = style.new_figure(width=10, height=4.6)
    y = np.arange(len(d))
    ax.hlines(y, d["abs_ci_low"] * 100, d["abs_ci_high"] * 100, color=style.BLUE, linewidth=2)
    ax.scatter(d["abs_diff"] * 100, y, color=style.BLUE, s=36, zorder=3)
    ax.axvline(0, color=style.TEXT_SECONDARY, linewidth=1)
    ax.axvline(thr * 100, color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    ax.text(
        thr * 100,
        len(d) - 0.45,
        f" practical threshold +{thr * 100:.1f} pp",
        fontsize=8.5,
        color=style.TEXT_SECONDARY,
    )
    ax.set_yticks(y)
    ax.set_yticklabels(d["scenario"])
    label_x = d["abs_ci_high"].max() * 100 + 0.6
    for yi, dec in enumerate(d["decision"]):
        ax.text(
            label_x, yi, dec, va="center", fontsize=9, fontweight="bold", color=style.TEXT_PRIMARY
        )
    ax.set_xlim(min(-2.5, d["abs_ci_low"].min() * 100 - 0.5), label_x + 3)
    ax.set_xlabel("Treatment minus control, purchase completion (percentage points)")
    ax.grid(axis="y", visible=False)
    style.finish(
        fig,
        "SIMULATED: primary metric and pre-registered decision per scenario",
        "Absolute difference with 95% Newcombe CI; ~21,000 synthetic users per scenario.",
        SIM_NOTE,
    )
    return style.save(fig, path)


def chart_guardrails(metrics: pd.DataFrame, path: Path) -> Path:
    g = metrics[metrics["role"] == "guardrail"]
    names = list(dict.fromkeys(g["metric"]))
    fig, axes = style.new_figure(ncols=len(names), width=13, height=4.4, sharey=True)
    status_color = {"green": style.BLUE, "amber": style.SERIES[3], "red": style.ORANGE}
    for ax, name in zip(axes, names, strict=True):
        d = g[g["metric"] == name].iloc[::-1].reset_index(drop=True)
        rel = d["margin_scale"].iloc[0] == "relative"
        est = (d["rel_diff"] if rel else d["abs_diff"]) * 100
        lo = (d["rel_ci_low"] if rel else d["abs_ci_low"]) * 100
        hi = (d["rel_ci_high"] if rel else d["abs_ci_high"]) * 100
        margin = (
            d["margin"].iloc[0] * 100 * (-1 if d["harmful_direction"].iloc[0] == "decrease" else 1)
        )
        y = np.arange(len(d))
        colors = [status_color[s] for s in d["guardrail_status"]]
        ax.hlines(y, lo, hi, color=colors, linewidth=2)
        ax.scatter(est, y, color=colors, s=30, zorder=3)
        ax.axvline(0, color=style.TEXT_SECONDARY, linewidth=1)
        ax.axvline(margin, color=style.ORANGE, linewidth=1, linestyle="--")
        for yi, (h, s) in enumerate(zip(hi, d["guardrail_status"], strict=True)):
            ax.text(
                max(h, margin) + 0.05,
                yi,
                f" {s}",
                va="center",
                fontsize=8.5,
                color=style.TEXT_PRIMARY,
            )
        ax.set_yticks(y)
        ax.set_yticklabels(d["scenario"])
        unit = "% relative" if rel else "pp"
        ax.set_title(f"{name}\n({unit}; dashed = margin)", fontsize=9.5)
        ax.grid(axis="y", visible=False)
    style.finish(
        fig,
        "SIMULATED: guardrails vs pre-registered margins",
        "95% CIs. green = harm beyond margin ruled out; amber = cannot rule out; red = significant"
        " harm. Status shown as text too.",
        SIM_NOTE,
    )
    return style.save(fig, path)


def chart_power(curve: pd.DataFrame, n_arm: float, mde: float, power: float, path: Path) -> Path:
    fig, ax = style.new_figure(width=8, height=4.6)
    ax.plot(curve["true_effect_abs"] * 100, curve["power"], color=style.BLUE)
    ax.axhline(power, color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    ax.axvline(mde * 100, color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    ax.text(mde * 100 + 0.05, 0.05, f"MDE {mde * 100:.2f} pp", fontsize=9, color=style.TEXT_PRIMARY)
    style.pct_axis(ax)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("True absolute lift in purchase completion (pp)")
    ax.set_ylabel("Power (two-sided, alpha 0.05)")
    style.finish(
        fig,
        f"Planned test: {n_arm:,.0f} users per arm detects {mde * 100:.2f} pp"
        f" with {power:.0%} power",
        "Analytic power of the two-proportion test at the planning baseline (assumed).",
        SIM_NOTE,
    )
    return style.save(fig, path)


def chart_validation(summary: pd.DataFrame, path: Path) -> Path:
    d = summary.iloc[::-1].reset_index(drop=True)
    fig, ax = style.new_figure(width=10, height=5.8)
    y = np.arange(len(d))
    ax.hlines(y, d["ci99_low"], d["ci99_high"], color=style.BLUE, linewidth=2)
    ax.scatter(d["observed_rate"], y, color=style.BLUE, s=30, zorder=3, label="Observed (99% CI)")
    ax.scatter(
        d["expected_rate"], y, marker="|", s=250, color=style.ORANGE, zorder=4, label="Expected"
    )
    ax.set_yticks(y)
    ax.set_yticklabels(d["check"], fontsize=8.5)
    style.pct_axis(ax, "x")
    ax.set_xlim(-0.02, 1.02)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2)
    ax.grid(axis="y", visible=False)
    style.finish(
        fig,
        "SIMULATED: repeated-simulation validation of the analysis",
        f"{int(summary['replications'].max())} replications per scenario"
        f" ({int(summary['replications'].min())} per SRM-loss check); expected = alpha,"
        " analytic power, 95% coverage or noncentral chi-square SRM power.",
        SIM_NOTE,
    )
    return style.save(fig, path)


def chart_aa_pvalues(reps: pd.DataFrame, path: Path) -> Path:
    p = reps.loc[reps["scenario"] == "aa", "p_value"]
    fig, ax = style.new_figure(width=8, height=4.4)
    ax.hist(p, bins=20, range=(0, 1), color=style.BLUE, edgecolor=style.SURFACE)
    ax.axhline(len(p) / 20, color=style.TEXT_SECONDARY, linestyle="--", linewidth=1)
    ax.set_xlabel("p-value of the primary test")
    ax.set_ylabel("Replications")
    ax.grid(axis="x", visible=False)
    style.finish(
        fig,
        "SIMULATED: A/A p-values are uniform, as they should be",
        f"{len(p)} A/A replications; dashed line = expected count per bin under H0.",
        SIM_NOTE,
    )
    return style.save(fig, path)


def chart_segments(seg: pd.DataFrame, scenario: str, path: Path) -> Path:
    d = seg[seg["scenario"] == scenario].iloc[::-1].reset_index(drop=True)
    fig, ax = style.new_figure(width=9, height=4.4)
    y = np.arange(len(d))
    ax.hlines(y, d["abs_ci_low"] * 100, d["abs_ci_high"] * 100, color=style.BLUE, linewidth=2)
    ax.scatter(d["abs_diff"] * 100, y, color=style.BLUE, s=30, zorder=3)
    ax.axvline(0, color=style.TEXT_SECONDARY, linewidth=1)
    labels = [
        f"{s}: {lvl} (n={min(nt, nc):,}/arm{', small' if small else ''})"
        for s, lvl, nt, nc, small in zip(
            d["segment"],
            d["level"],
            d["n_treatment"],
            d["n_control"],
            d["small_sample"],
            strict=True,
        )
    ]
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8.5)
    for yi, (hi, q) in enumerate(zip(d["abs_ci_high"], d["p_value_bh"], strict=True)):
        ax.text(
            hi * 100 + 0.2, yi, f"BH p={q:.3f}", va="center", fontsize=8, color=style.TEXT_SECONDARY
        )
    ax.set_xlabel("Treatment minus control, purchase completion (pp)")
    ax.grid(axis="y", visible=False)
    style.finish(
        fig,
        f"SIMULATED: pre-registered segments, '{scenario}' scenario (exploratory)",
        "95% unadjusted CIs; Benjamini-Hochberg adjusted p-values. Not a basis for segment-only"
        " launch.",
        SIM_NOTE,
    )
    return style.save(fig, path)


def run_experiment(
    settings: Settings,
    replications: int | None = None,
    n_users: int | None = None,
) -> ExperimentResult:
    cfg = settings.section("experiment")
    design, population, scenarios = load_experiment(cfg)
    by_name = {s.name: s for s in scenarios}
    base_seed = int(cfg["seed"])
    results_dir = settings.paths.results_dir / "experiment"
    fig_dir = settings.paths.figures_dir / "experiment"
    results_dir.mkdir(parents=True, exist_ok=True)

    sims = [
        simulate_experiment(design, population, s, seed=base_seed + 1000 * i, n_users=n_users)
        for i, s in enumerate(scenarios)
    ]
    users = pd.concat([s.users for s in sims], ignore_index=True)
    events = pd.concat([s.assignment_events for s in sims], ignore_index=True)
    outcomes = pd.concat([s.outcomes for s in sims], ignore_index=True)
    truth = pd.DataFrame([s.truth for s in sims])

    tables: dict[str, pd.DataFrame] = {}
    con = connect(settings.paths.warehouse)
    try:
        # Truth is stored apart from the analysis dataset.
        for name, df in [("users", users), ("assignment_events", events), ("outcomes", outcomes)]:
            _write(con, name, df)
        _write(con, "simulation_truth_validation_only", truth)
        logger.info("Wrote SIMULATED tables: %d users, %d exposures", len(users), len(events))

        run_sql_layer(con, "sim")
        tables["quality_checks"] = pd.DataFrame(
            [r.__dict__ for r in run_quality_checks(con, prefix="sim_")]
        )
        fct = con.execute("SELECT * FROM sim.fct_experiment_users").df()
        agg = con.execute("SELECT * FROM sim.agg_variant_metrics").df()
        tables["variant_metrics"] = agg

        metric_rows, decision_rows, srm_rows, segment_rows, problems = [], [], [], [], []
        for scen in scenarios:
            df = fct[fct["scenario"] == scen.name]
            srm = srm_check(df, design.treatment_share, design.srm_alpha)
            metrics = analyze_metrics(df, design)
            problems += reconcile_sql_python(agg, metrics, scen.name)
            dec = decide(metrics, srm, design, aa_test=scen.identical_arms)
            seg = segment_analysis(df, design)
            metric_rows.append(metrics.assign(scenario=scen.name))
            srm_rows.append({"scenario": scen.name, **srm})
            segment_rows.append(seg.assign(scenario=scen.name))
            decision_rows.append(
                {
                    "scenario": scen.name,
                    "description": scen.description,
                    "decision": dec.decision,
                    "reasons": " ".join(dec.reasons),
                }
            )
        if problems:
            raise ExperimentReconciliationError("\n".join(problems))
        logger.info("SQL vs Python experiment metrics reconcile for %d scenarios", len(scenarios))

        tables["metric_results"] = pd.concat(metric_rows, ignore_index=True)
        tables["decisions"] = pd.DataFrame(decision_rows)
        tables["srm_checks"] = pd.DataFrame(srm_rows)
        tables["segment_results"] = pd.concat(segment_rows, ignore_index=True)

        # Power is planned from the planning baseline, not the simulation truth.
        n_total = n_users or design.planned_users
        n_arm = n_total * min(design.treatment_share, 1 - design.treatment_share)
        p0 = design.planning_baseline_conversion
        mde = mde_for_n(p0, n_arm, design.alpha, design.power)
        tables["power_plan"] = pd.DataFrame(
            [
                {
                    "planning_baseline": p0,
                    "alpha": design.alpha,
                    "power": design.power,
                    "target_mde_abs": design.mde_abs,
                    "required_n_per_arm_statsmodels": required_n_per_arm(
                        p0, design.mde_abs, design.alpha, design.power
                    ),
                    "required_n_per_arm_closed_form": required_n_closed_form(
                        p0, design.mde_abs, design.alpha, design.power
                    ),
                    "planned_users_total": n_total,
                    "planned_n_per_arm": n_arm,
                    "achieved_mde_abs": mde,
                    "duration_days": design.duration_days,
                    "practical_threshold_abs": design.practical_threshold_abs,
                }
            ]
        )
        tables["power_curve"] = power_curve(p0, n_arm, np.round(np.arange(0, 0.0401, 0.001), 4))
        # Guardrail sensitivity: A/A control arm stands in for pre-period data.
        aa = [sc.name for sc in scenarios if sc.identical_arms]
        if aa:
            proxy = fct[(fct["scenario"] == aa[0]) & (fct["variant"] == "control")]
            tables["guardrail_sensitivity"] = guardrail_sensitivity(
                proxy, design.guardrail_margins, n_arm, design.alpha, design.power
            )
    finally:
        con.close()

    # Runs with the warehouse closed so the multi-minute validation never holds the lock.
    vcfg = cfg["validation"]
    reps = int(replications or vcfg["replications"])
    tables["validation_summary"], tables["validation_replications"] = run_validation(
        design,
        population,
        by_name,
        reps,
        base_seed + 7,
        [float(x) for x in vcfg["srm_logging_losses"]],
        n_users=n_users,
    )

    con = connect(settings.paths.warehouse)
    try:
        for name in (
            "metric_results",
            "decisions",
            "srm_checks",
            "segment_results",
            "power_plan",
            "power_curve",
            "guardrail_sensitivity",
            "validation_summary",
        ):
            _write(con, name, tables[name])
    finally:
        con.close()

    for name, df in tables.items():
        df.to_csv(results_dir / f"{name}.csv", index=False)
    truth.to_csv(results_dir / "simulation_truth_validation_only.csv", index=False)

    figures = [
        chart_primary(
            tables["metric_results"],
            tables["decisions"],
            design.practical_threshold_abs,
            fig_dir / "01_primary_by_scenario.png",
        ),
        chart_guardrails(tables["metric_results"], fig_dir / "02_guardrails.png"),
        chart_power(
            tables["power_curve"], n_arm, mde, design.power, fig_dir / "03_power_curve.png"
        ),
        chart_segments(tables["segment_results"], "positive", fig_dir / "04_segments_positive.png"),
        chart_validation(tables["validation_summary"], fig_dir / "05_validation.png"),
        chart_aa_pvalues(tables["validation_replications"], fig_dir / "06_aa_pvalues.png"),
    ]
    numbers = {
        "decisions": dict(
            zip(tables["decisions"]["scenario"], tables["decisions"]["decision"], strict=True)
        ),
        "planned_n_per_arm": n_arm,
        "achieved_mde_abs": mde,
    }
    (results_dir / "key_numbers.json").write_text(json.dumps(numbers, indent=2))
    return ExperimentResult(tables, figures, numbers)
