"""Regression analysis of the SIMULATED checkout experiment.

Reads the analysis dataset written by ``reporting/experiment.py`` (sim.fct_experiment_users),
fits the unadjusted / adjusted / interaction logits per scenario, cross-checks them against
the primary two-proportion analysis, validates the adjusted estimator by repeated
simulation and writes tables (sim.regression_*), CSVs and charts. Everything is SIMULATED.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from marketplace_analytics.config import Settings
from marketplace_analytics.data.warehouse import connect
from marketplace_analytics.experiments.design import load_experiment
from marketplace_analytics.experiments.power import power_for_effect
from marketplace_analytics.experiments.regression import (
    device_effects,
    fit_models,
    interaction_test,
    mediator_bias_demo,
    model_frame,
    treatment_effects,
)
from marketplace_analytics.experiments.validation import replicate_adjusted, summarise_adjusted
from marketplace_analytics.reporting import style
from marketplace_analytics.statistics.regression import tidy

logger = logging.getLogger(__name__)

SIM_NOTE = style.SIMULATED_SOURCE
MODEL_LABELS = {
    "raw_difference": "Two-proportion difference (primary)",
    "unadjusted": "Logit, unadjusted (AME)",
    "adjusted": "Logit, adjusted for device + customer type (AME)",
}


class ExperimentRegressionError(RuntimeError):
    """The regression disagrees with the primary analysis where it must agree exactly."""


@dataclass
class ExperimentRegressionResult:
    tables: dict[str, pd.DataFrame]
    figures: list[Path] = field(default_factory=list)
    key_numbers: dict = field(default_factory=dict)


def chart_ame_by_model(effects: pd.DataFrame, path: Path) -> Path:
    scenarios = list(dict.fromkeys(effects["scenario"]))[::-1]
    models = list(MODEL_LABELS)
    fig, ax = style.new_figure(width=10, height=5.4)
    offsets = np.linspace(0.22, -0.22, len(models))
    for model, off, color in zip(models, offsets, style.SERIES, strict=False):
        d = effects[effects["model"] == model].set_index("scenario").loc[scenarios]
        y = np.arange(len(scenarios)) + off
        ax.hlines(y, d["ame_ci_low"] * 100, d["ame_ci_high"] * 100, color=color, linewidth=2)
        ax.scatter(d["ame_abs"] * 100, y, color=color, s=26, zorder=3, label=MODEL_LABELS[model])
    ax.axvline(0, color=style.TEXT_SECONDARY, linewidth=1)
    ax.set_yticks(np.arange(len(scenarios)))
    ax.set_yticklabels(scenarios)
    ax.set_xlabel("Treatment effect on purchase completion (percentage points, 95% CI)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=1, fontsize=8.5)
    ax.grid(axis="y", visible=False)
    style.finish(
        fig,
        "SIMULATED: regression estimates agree with the primary analysis",
        "Average marginal effects (pp). Unadjusted logit reproduces the raw difference;"
        " adjustment uses pre-treatment covariates only.",
        SIM_NOTE,
    )
    return style.save(fig, path)


def chart_device_effects(dev: pd.DataFrame, overall: pd.Series, lr: dict, path: Path) -> Path:
    d = dev.iloc[::-1].reset_index(drop=True)
    fig, ax = style.new_figure(width=10, height=5)
    y = np.arange(len(d))
    ax.axvspan(
        overall["ame_ci_low"] * 100,
        overall["ame_ci_high"] * 100,
        color=style.BLUE,
        alpha=0.12,
        linewidth=0,
        label="Overall adjusted AME (95% CI)",
    )
    ax.axvline(overall["ame_abs"] * 100, color=style.BLUE, linewidth=1, linestyle="--")
    ax.hlines(
        y, d["ame_ci_low"] * 100, d["ame_ci_high"] * 100, color=style.TEXT_PRIMARY, linewidth=2
    )
    ax.scatter(
        d["ame_abs"] * 100,
        y,
        color=style.TEXT_PRIMARY,
        s=30,
        zorder=3,
        label="Device-specific AME (95% CI)",
    )
    for yi, (hi, p0, p1, orr) in enumerate(
        zip(
            d["ame_ci_high"],
            d["pred_control"],
            d["pred_treatment"],
            d["implied_odds_ratio"],
            strict=True,
        )
    ):
        ax.text(
            hi * 100 + 0.2,
            yi,
            f"{p0:.1%} -> {p1:.1%}  (OR {orr:.2f})",
            va="center",
            fontsize=8.5,
            color=style.TEXT_SECONDARY,
        )
    ax.axvline(0, color=style.TEXT_SECONDARY, linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{dv} (n={n:,})" for dv, n in zip(d["device"], d["users"], strict=True)])
    ax.set_xlim(right=d["ame_ci_high"].max() * 100 + 4)
    ax.set_xlabel("Treatment effect on purchase completion (pp)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=8.5)
    ax.grid(axis="y", visible=False)
    style.finish(
        fig,
        f"SIMULATED 'positive': treatment x device interaction LR test p = {lr['p_value']:.2f}",
        "Device-specific effects from the interaction model; labels show control -> treatment"
        " predicted completion and the implied odds ratio.",
        SIM_NOTE,
    )
    return style.save(fig, path)


def chart_mediator(demo: pd.DataFrame, path: Path) -> Path:
    d = demo.iloc[::-1].reset_index(drop=True)
    fig, ax = style.new_figure(width=9, height=3.8)
    y = np.arange(len(d))
    truth = d["ci_low"].isna()
    ax.barh(y[truth], d.loc[truth, "estimate"] * 100, color="#c9c7c0", height=0.5)
    ax.scatter(d.loc[~truth, "estimate"] * 100, y[~truth], color=style.BLUE, s=34, zorder=3)
    ax.hlines(
        y[~truth],
        d.loc[~truth, "ci_low"] * 100,
        d.loc[~truth, "ci_high"] * 100,
        color=style.BLUE,
        linewidth=2,
    )
    for yi, v in zip(y, d["estimate"], strict=True):
        ax.text(
            max(v * 100, 0) + 0.15,
            yi + 0.18,
            f"{v * 100:+.2f} pp",
            fontsize=8.5,
            color=style.TEXT_PRIMARY,
        )
    ax.axvline(0, color=style.TEXT_SECONDARY, linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(d["quantity"])
    ax.set_xlabel("Effect of treatment on purchase completion (pp)")
    ax.grid(axis="y", visible=False)
    style.finish(
        fig,
        "SIMULATED toy world: adjusting for a post-treatment variable hides the effect",
        "Treatment cuts errors; errors cut purchases. Grey = truth; blue = mean of"
        f" {int(demo['replications'].iloc[0])} toy experiments (2.5-97.5% range).",
        SIM_NOTE,
    )
    return style.save(fig, path)


def chart_ci_width(reps: pd.DataFrame, path: Path) -> Path:
    ratio = reps["adjusted_ci_width"] / reps["unadjusted_ci_width"]
    fig, ax = style.new_figure(width=8, height=4.2)
    ax.hist(ratio, bins=25, color=style.BLUE, edgecolor=style.SURFACE)
    ax.axvline(1, color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    ax.set_xlabel("Adjusted / unadjusted logit CI width (delta method, same simulated data)")
    ax.set_ylabel("Replications")
    ax.grid(axis="x", visible=False)
    style.finish(
        fig,
        f"SIMULATED: covariate adjustment narrows the CI by {1 - ratio.mean():.1%} on average",
        f"{len(reps)} replications; gain is small because device and customer type predict"
        " purchase only weakly.",
        SIM_NOTE,
    )
    return style.save(fig, path)


def run_experiment_regression(
    settings: Settings, replications: int | None = None, n_users: int | None = None
) -> ExperimentRegressionResult:
    cfg = settings.section("experiment")
    rcfg = cfg["regression"]
    design, population, scenarios = load_experiment(cfg)
    by_name = {s.name: s for s in scenarios}
    n_draws, seed = int(rcfg["simulation_draws"]), int(rcfg["seed"])
    results_dir = settings.paths.results_dir / "experiment_regression"
    fig_dir = settings.paths.figures_dir / "experiment_regression"
    results_dir.mkdir(parents=True, exist_ok=True)

    con = connect(settings.paths.warehouse)
    try:
        fct = con.execute("SELECT * FROM sim.fct_experiment_users").df()
        primary = con.execute(
            "SELECT scenario, abs_diff, abs_ci_low, abs_ci_high, p_value "
            "FROM sim.metric_results WHERE metric = 'purchase_completion'"
        ).df()
    except Exception as exc:  # noqa: BLE001 - give the user the next step, not a stack trace
        con.close()
        raise ExperimentRegressionError(
            "Simulated experiment tables not found; run `marketplace_analytics experiment` first"
        ) from exc
    con.close()

    effect_rows, coef_rows, inter_rows, dev_rows, problems = [], [], [], [], []
    fits_by_scenario = {}
    for scen in scenarios:
        frame = model_frame(fct[fct["scenario"] == scen.name])
        fits = fit_models(frame)
        fits_by_scenario[scen.name] = fits
        te = treatment_effects(fits, n_draws, seed).assign(scenario=scen.name)
        raw = primary.set_index("scenario").loc[scen.name]
        effect_rows.append(
            pd.DataFrame(
                [
                    {
                        "scenario": scen.name,
                        "model": "raw_difference",
                        "n": len(frame),
                        "ame_abs": raw["abs_diff"],
                        "ame_ci_low": raw["abs_ci_low"],
                        "ame_ci_high": raw["abs_ci_high"],
                        "ame_ci_width": raw["abs_ci_high"] - raw["abs_ci_low"],
                        "or_p_value": raw["p_value"],
                    }
                ]
            )
        )
        effect_rows.append(te)
        unadj = te.set_index("model").loc["unadjusted", "ame_abs"]
        if not np.isclose(unadj, raw["abs_diff"], atol=1e-9):
            problems.append(f"{scen.name}: unadjusted AME {unadj} != raw diff {raw['abs_diff']}")
        for name, fit in fits.items():
            coef_rows.append(tidy(fit).assign(scenario=scen.name, model=name))
        inter_rows.append({"scenario": scen.name, **interaction_test(fits)})
        dev_rows.append(
            device_effects(fits["interaction"], n_draws, seed).assign(scenario=scen.name)
        )
    if problems:
        raise ExperimentRegressionError("\n".join(problems))
    logger.info(
        "Unadjusted logit AME equals the raw difference in all %d scenarios", len(scenarios)
    )

    tables = {
        "treatment_effects": pd.concat(effect_rows, ignore_index=True),
        "coefficients": pd.concat(coef_rows, ignore_index=True),
        "interaction_tests": pd.DataFrame(inter_rows),
        "device_effects": pd.concat(dev_rows, ignore_index=True),
        "mediator_demo": mediator_bias_demo(seed=seed),
    }

    # Repeated-simulation validation of the adjusted estimator.
    reps_n = int(replications or rcfg["validation_replications"])
    n = n_users or design.planned_users
    baseline = population.expected_baseline_conversion()
    summary, all_reps = [], []
    for i, name in enumerate(["aa", "positive"]):
        scen = by_name[name]
        logger.info("Adjusted-model validation: %s x %d replications", name, reps_n)
        reps = replicate_adjusted(design, population, scen, reps_n, seed + 10 + i, n)
        all_reps.append(reps)
        effect = 0.0 if scen.identical_arms else scen.conversion_abs
        expected = design.alpha if effect == 0 else power_for_effect(baseline, effect, n / 2)
        summary += summarise_adjusted(reps, design, expected)
    tables["validation_summary"] = pd.DataFrame(summary)
    tables["validation_replications"] = pd.concat(all_reps, ignore_index=True)

    con = connect(settings.paths.warehouse)
    try:
        for name in (
            "treatment_effects",
            "coefficients",
            "interaction_tests",
            "device_effects",
            "mediator_demo",
            "validation_summary",
        ):
            con.register("_df", tables[name])
            con.execute(f"CREATE OR REPLACE TABLE sim.regression_{name} AS SELECT * FROM _df")
            con.unregister("_df")
    finally:
        con.close()
    for name, df in tables.items():
        df.to_csv(results_dir / f"{name}.csv", index=False)

    pos = "positive" if "positive" in by_name else scenarios[0].name
    effects = tables["treatment_effects"]
    overall = effects[(effects["scenario"] == pos) & (effects["model"] == "adjusted")].iloc[0]
    lr = tables["interaction_tests"].set_index("scenario").loc[pos]
    figures = [
        chart_ame_by_model(effects, fig_dir / "01_ame_by_model.png"),
        chart_device_effects(
            tables["device_effects"].query("scenario == @pos"),
            overall,
            lr,
            fig_dir / "02_device_effects_positive.png",
        ),
        chart_mediator(tables["mediator_demo"], fig_dir / "03_post_treatment_bias.png"),
        chart_ci_width(
            tables["validation_replications"].query("scenario == @pos"),
            fig_dir / "04_ci_width_gain.png",
        ),
    ]
    numbers = {
        "interaction_p_values": dict(
            zip(
                tables["interaction_tests"]["scenario"],
                tables["interaction_tests"]["p_value"],
                strict=True,
            )
        ),
        "validation_consistent": bool(
            tables["validation_summary"]["consistent"].dropna().astype(bool).all()
        ),
    }
    (results_dir / "key_numbers.json").write_text(json.dumps(numbers, indent=2))
    return ExperimentRegressionResult(tables, figures, numbers)
