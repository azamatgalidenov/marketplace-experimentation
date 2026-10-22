"""Run the observational low-review regression and write its tables, charts and numbers.

All estimates are observational associations on real Olist data.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.contingency_tables import StratifiedTable

from marketplace_analytics.config import Settings
from marketplace_analytics.data.warehouse import connect, set_variables
from marketplace_analytics.reporting import style
from marketplace_analytics.statistics import low_review_model as lrm
from marketplace_analytics.statistics.regression import (
    LogitFit,
    average_marginal_effect,
    average_predictions,
    calibration_table,
    cooks_distance,
    fit_logit,
    influential_mask,
    performance,
    tidy,
    vif_table,
)

logger = logging.getLogger(__name__)


@dataclass
class RegressionResult:
    frame: pd.DataFrame
    refs: lrm.References
    fits: dict[str, LogitFit]
    tables: dict[str, pd.DataFrame]
    figures: list[Path] = field(default_factory=list)
    key_numbers: dict = field(default_factory=dict)


def top_late_sellers(frame: pd.DataFrame, k: int) -> list[str]:
    """Sellers with the most late orders among post-delivery surveys."""
    late_post = frame[(frame["late"] == 1) & (frame["timing"] == "post")]
    return list(late_post["seller"].value_counts().index[:k])


def fit_specs(
    frame: pd.DataFrame, specs: list[lrm.ModelSpec], cluster: str = "seller"
) -> tuple[dict[str, LogitFit], dict[str, int]]:
    fits: dict[str, LogitFit] = {}
    dropped: dict[str, int] = {}
    for spec in specs:
        data = frame.query(spec.sample) if spec.sample else frame
        k = spec.extra.get("exclude_top_late_sellers")
        if k:
            excluded = data["seller"].isin(top_late_sellers(data, k))
            dropped[spec.name] = int(excluded.sum())
            data = data.loc[~excluded]
        logger.info("Fitting %s (%s): n=%d", spec.name, spec.label, len(data))
        fits[spec.name] = fit_logit(spec.formula, data, cluster=cluster)
    return fits, dropped


def influence_diagnostics(fit: LogitFit, frame: pd.DataFrame, top_share: float = 0.01) -> dict:
    """Describe the most influential observations of a fit and what removing them does.

    Reported as a diagnostic, not used as a robustness specification: with a rare
    predictor the most influential points are largely the late orders with low reviews,
    so deleting them removes the association being studied.
    """
    cooks = cooks_distance(fit)
    top = influential_mask(fit, top_share)
    data = fit.data
    refit = fit_logit(fit.formula, data.loc[~top], cluster=fit.cluster)
    t = tidy(refit).set_index("term").loc["late"]
    flagged = data.loc[top]
    return {
        "n": len(data),
        "flagged_4_over_n": int((cooks > 4 / len(cooks)).sum()),
        "flagged_top_share": int(top.sum()),
        "top_share": top_share,
        "late_share_all": float(data["late"].mean()),
        "late_share_flagged": float(flagged["late"].mean()),
        "low_review_share_all": float(data["low_review"].mean()),
        "low_review_share_flagged": float(flagged["low_review"].mean()),
        "late_post_low_in_flagged": int(
            (
                (flagged["late"] == 1)
                & (flagged["timing"] == "post")
                & (flagged["low_review"] == 1)
            ).sum()
        ),
        "late_post_low_all": int(
            ((data["late"] == 1) & (data["timing"] == "post") & (data["low_review"] == 1)).sum()
        ),
        "late_or_after_removal": float(t["odds_ratio"]),
        "late_or_ci_low_after_removal": float(t["or_ci_low"]),
        "late_or_ci_high_after_removal": float(t["or_ci_high"]),
    }


def late_or_by_timing(fit: LogitFit, late_term: str, timing_var: str) -> pd.DataFrame:
    """Odds ratio of late vs on-time within each survey-timing class (linear combinations
    of the main effect and the interaction, with the fit's covariance)."""
    res = fit.result
    rows = []
    pattern = re.compile(rf"^{late_term}:C\({timing_var}, Treatment\('(\w+)'\)\)\[T\.(\w+)\]$")
    ref = None
    combos = {}
    for name in res.params.index:
        m = pattern.match(name)
        if m:
            ref = m.group(1)
            combos[m.group(2)] = name
    levels = [ref or "post", *combos]
    for level in levels:
        weights = pd.Series(0.0, index=res.params.index)
        weights[late_term] = 1.0
        if level in combos:
            weights[combos[level]] = 1.0
        est = float(weights @ res.params)
        se = float(np.sqrt(weights @ res.cov_params() @ weights))
        rows.append(
            {
                "timing": level,
                "odds_ratio": np.exp(est),
                "or_ci_low": np.exp(est - 1.959964 * se),
                "or_ci_high": np.exp(est + 1.959964 * se),
            }
        )
    return pd.DataFrame(rows)


def comparison_table(
    fits: dict[str, LogitFit],
    specs: list[lrm.ModelSpec],
    dropped: dict[str, int],
    n_draws: int,
    seed: int,
) -> pd.DataFrame:
    rows = []
    for spec in specs:
        fit = fits[spec.name]
        t = tidy(fit).set_index("term").loc[spec.late_term]
        perf = performance(fit)
        subset = fit.data.eval(spec.ame_population) if spec.ame_population else None
        ame = average_marginal_effect(
            fit, spec.late_term, 1, 0, subset=subset, n_draws=n_draws, seed=seed
        )
        late_in = fit.data if subset is None else fit.data.loc[subset]
        rows.append(
            {
                "spec": spec.name,
                "label": spec.label,
                "group": spec.group,
                "n": perf["n"],
                "low_reviews": perf["events"],
                "late_orders": int(fit.data[spec.late_term].sum()),
                "late_orders_in_ame_population": int(late_in[spec.late_term].sum()),
                "ame_population_n": ame["n"],
                "excluded_rows": dropped.get(spec.name, 0),
                "late_or": t["odds_ratio"],
                "late_or_ci_low": t["or_ci_low"],
                "late_or_ci_high": t["or_ci_high"],
                "late_p_value": t["p_value"],
                "late_ame_pp": ame["ame"] * 100,
                "late_ame_ci_low_pp": ame["ame_ci_low"] * 100,
                "late_ame_ci_high_pp": ame["ame_ci_high"] * 100,
                "auc": perf["auc"],
                "mcfadden_r2": perf["mcfadden_r2"],
                "parameters": perf["parameters"],
                "notes": spec.notes,
            }
        )
    return pd.DataFrame(rows)


COVARIATE_CHANGES = [
    ("late", "Late vs on time", 1, 0),
    ("basket", "Several items, one seller vs single item", "multi_item_one_seller", "single_item"),
    ("basket", "Several sellers vs single item", "multi_seller", "single_item"),
    ("promised_weeks", "Promise one week longer", lambda x: x + 1, lambda x: x),
    ("freight_share_10pp", "Freight share +10 pp", lambda x: x + 1, lambda x: x),
    ("log_items_value", "Item value doubled", lambda x: x + np.log(2), lambda x: x),
]


def covariate_effects(fit: LogitFit, n_draws: int, seed: int) -> pd.DataFrame:
    """Average marginal effects (percentage points) for the main non-categorical terms."""
    rows = []
    for variable, label, treated, reference in COVARIATE_CHANGES:
        ame = average_marginal_effect(fit, variable, treated, reference, n_draws=n_draws, seed=seed)
        rows.append(
            {
                "variable": variable,
                "change": label,
                "ame_pp": ame["ame"] * 100,
                "ci_low_pp": ame["ame_ci_low"] * 100,
                "ci_high_pp": ame["ame_ci_high"] * 100,
                "n": ame["n"],
            }
        )
    return pd.DataFrame(rows)


def cmh_test(frame: pd.DataFrame, strata: str, outcome: str = "low_review") -> dict:
    """Cochran-Mantel-Haenszel test of late vs low review, stratified by ``strata``."""
    tables = []
    for _, g in frame.groupby(strata):
        t = pd.crosstab(g["late"], g[outcome]).reindex(index=[1, 0], columns=[1, 0], fill_value=0)
        if (t.sum(axis=1) > 0).all():
            tables.append(t.to_numpy())
    st = StratifiedTable(tables)
    test = st.test_null_odds(correction=True)
    homog = st.test_equal_odds(adjust=True)
    lo, hi = st.oddsratio_pooled_confint()
    return {
        "strata_variable": strata,
        "strata_used": len(tables),
        "n": int(sum(t.sum() for t in tables)),
        "pooled_or": float(st.oddsratio_pooled),
        "or_ci_low": float(lo),
        "or_ci_high": float(hi),
        "cmh_statistic": float(test.statistic),
        "cmh_p_value": float(test.pvalue),
        "homogeneity_p_value": float(homog.pvalue),
    }


def cross_tab(frame: pd.DataFrame) -> pd.DataFrame:
    """Orders and low-review rate by delay category and survey timing."""
    g = frame.groupby(["timing", "delay_cat"])["low_review"].agg(["size", "sum", "mean"])
    g.columns = ["orders", "low_reviews", "low_review_rate"]
    return g.reset_index()


_C_TERM = re.compile(r"^C\((\w+), Treatment\('[^']*'\)\)\[T\.(.+)\]$")
LABELS = {
    "late": "Late delivery",
    "late_ts": "Late delivery (timestamp definition)",
    "promised_weeks": "Promised delivery time (+1 week)",
    "log_items_value": "Order item value (x2.72, log scale)",
    "freight_share_10pp": "Freight share of order value (+10 pp)",
}


def term_label(term: str) -> str:
    parts = []
    for piece in term.split(":"):
        m = _C_TERM.match(piece)
        if m:
            var, level = m.groups()
            parts.append(
                {
                    "timing": f"Survey {'sent before delivery' if level == 'pre' else 'same day'}",
                    "timing_answer": "Survey answered before delivery",
                    "category": f"Category: {level}",
                    "region": f"Region: {level}",
                    "month": f"Month: {level}",
                    "cell": f"Cell: {level}",
                    "basket": {
                        "multi_item_one_seller": "Several items, one seller",
                        "multi_seller": "Several sellers",
                    }.get(level, f"Basket: {level}"),
                }.get(var, f"{var}: {level}")
            )
        else:
            parts.append(LABELS.get(piece, piece))
    return " x ".join(parts)


def term_group(term: str) -> str:
    if term.startswith("C(category"):
        return "Product category"
    if term.startswith("C(region"):
        return "Customer region"
    if term.startswith("C(month"):
        return "Purchase month"
    if term in {"log_items_value", "freight_share_10pp"} or term.startswith("C(basket"):
        return "Order"
    return "Delivery & survey timing"


def chart_coefficients(coefs: pd.DataFrame, title: str, subtitle: str, path: Path) -> Path:
    d = coefs[(coefs["term"] != "Intercept") & (coefs["group"] != "Purchase month")].copy()
    order = ["Delivery & survey timing", "Order", "Customer region", "Product category"]
    d["g"] = d["group"].map({g: i for i, g in enumerate(order)})
    d = d.sort_values(["g", "odds_ratio"], ascending=[False, True]).reset_index(drop=True)
    fig, ax = style.new_figure(width=9.5, height=max(5, 0.27 * len(d) + 1.6))
    y = np.arange(len(d))
    significant = (d["or_ci_low"] > 1) | (d["or_ci_high"] < 1)
    colors = np.where(significant, style.BLUE, "#9a9893")
    ax.hlines(y, d["or_ci_low"], d["or_ci_high"], color=colors, linewidth=1.6)
    ax.scatter(d["odds_ratio"], y, color=colors, s=22, zorder=3)
    ax.axvline(1, color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    ax.set_xscale("log")
    ax.set_yticks(y)
    ax.set_yticklabels(d["label"], fontsize=8.5)
    ax.set_xlabel("Odds ratio for a low review (log scale, 95% cluster-robust CI)")
    ax.grid(axis="y", visible=False)
    for i in range(1, len(d)):
        if d.loc[i, "g"] != d.loc[i - 1, "g"]:
            ax.axhline(i - 0.5, color=style.GRID, linewidth=1)
    ax.xaxis.set_major_formatter(style.FuncFormatter(lambda v, _: f"{v:g}"))
    style.finish(fig, title, subtitle)
    return style.save(fig, path)


def chart_spec_comparison(comp: pd.DataFrame, path: Path) -> Path:
    d = comp.iloc[::-1].reset_index(drop=True)
    labels = [f"{s}  {lab}" for s, lab in zip(d["spec"], d["label"], strict=True)]
    fig, (a1, a2) = style.new_figure(ncols=2, width=12, height=6.2, sharey=True)
    y = np.arange(len(d))
    color = [style.BLUE if g == "main" else style.ORANGE for g in d["group"]]
    a1.hlines(y, d["late_or_ci_low"], d["late_or_ci_high"], color=color, linewidth=1.8)
    a1.scatter(d["late_or"], y, color=color, s=26, zorder=3)
    a1.axvline(1, color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    a1.set_xscale("log")
    a1.xaxis.set_major_formatter(style.FuncFormatter(lambda v, _: f"{v:g}"))
    a1.set_title("Odds ratio, late vs on time")
    a2.hlines(y, d["late_ame_ci_low_pp"], d["late_ame_ci_high_pp"], color=color, linewidth=1.8)
    a2.scatter(d["late_ame_pp"], y, color=color, s=26, zorder=3)
    a2.axvline(0, color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    a2.set_title("Average marginal effect (percentage points)")
    a1.set_yticks(y)
    a1.set_yticklabels(labels, fontsize=8.5)
    for ax in (a1, a2):
        ax.grid(axis="y", visible=False)
    style.finish(
        fig,
        "Late-delivery association across model specifications",
        "Blue = main specifications, orange = sensitivity analyses. Effects for orders"
        " surveyed after delivery (see notes per spec). 95% cluster-robust intervals.",
    )
    return style.save(fig, path)


def chart_cells(pred: pd.DataFrame, counts: pd.DataFrame, title: str, path: Path) -> Path:
    d = pred.merge(counts, left_on="level", right_on="cell")
    d["timing"] = d["level"].str.split("|").str[1]
    d["delay"] = d["level"].str.split("|").str[0]
    timing_order = {"post": 0, "same_day": 1, "pre": 2}
    delay_order = {"on_time": 0, "late_1_3": 1, "late_4_plus": 2, "late_4_7": 3, "late_8_plus": 4}
    d = d.sort_values(
        by=["timing", "delay"],
        key=lambda s: s.map(timing_order) if s.name == "timing" else s.map(delay_order),
    ).reset_index(drop=True)
    fig, ax = style.new_figure(width=10, height=5)
    x = np.arange(len(d))
    names = {"post": "Survey after delivery", "same_day": "Same day", "pre": "Survey before"}
    color = [
        style.BLUE if t == "post" else (style.SERIES[2] if t == "same_day" else style.ORANGE)
        for t in d["timing"]
    ]
    ax.bar(x, d["probability"], color=color, width=0.65)
    ax.errorbar(
        x,
        d["probability"],
        yerr=[d["probability"] - d["ci_low"], d["ci_high"] - d["probability"]],
        fmt="none",
        ecolor=style.TEXT_PRIMARY,
        capsize=3,
        linewidth=1,
    )
    for xi, (hi, p, n) in enumerate(zip(d["ci_high"], d["probability"], d["orders"], strict=True)):
        ax.text(
            xi, hi + 0.02, f"{p:.0%}\nn={n:,}", ha="center", fontsize=8, color=style.TEXT_PRIMARY
        )
    delay_names = {
        "on_time": "On time",
        "late_1_3": "1-3 d\nlate",
        "late_4_7": "4-7 d\nlate",
        "late_8_plus": "8+ d\nlate",
        "late_4_plus": "4+ d\nlate",
    }
    ax.set_xticks(x)
    ax.set_xticklabels([delay_names.get(v, v) for v in d["delay"]], fontsize=8.5)
    for t in ["post", "same_day", "pre"]:
        idx = np.where(d["timing"] == t)[0]
        if len(idx):
            ax.text(
                idx.mean(),
                -0.17,
                names[t],
                ha="center",
                fontsize=9,
                fontweight="bold",
                color=style.TEXT_PRIMARY,
                transform=ax.get_xaxis_transform(),
            )
    style.pct_axis(ax)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Adjusted predicted probability of a low review")
    ax.grid(axis="x", visible=False)
    style.finish(
        fig,
        title,
        "Average adjusted predictions from the cell model (covariates at observed values),"
        " 95% simulation intervals. Observational.",
    )
    return style.save(fig, path)


def chart_calibration(tables: dict[str, pd.DataFrame], path: Path) -> Path:
    fig, ax = style.new_figure(width=6.5, height=5.5)
    ax.plot([0, 1], [0, 1], color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    for (name, t), color in zip(tables.items(), style.SERIES, strict=False):
        ax.plot(t["predicted"], t["observed"], marker="o", color=color, label=name, markersize=5)
    style.pct_axis(ax)
    style.pct_axis(ax, "x")
    ax.set_xlabel("Mean predicted probability (decile)")
    ax.set_ylabel("Observed low-review rate")
    ax.legend(loc="upper left")
    style.finish(fig, "Calibration by decile of predicted risk", "In-sample; dashed = perfect")
    return style.save(fig, path)


def run_regression(settings: Settings, frame: pd.DataFrame | None = None) -> RegressionResult:
    """Fit every specification and write outputs.

    ``frame`` can be supplied (tests); otherwise the model frame is built from the warehouse.
    """
    cfg = settings.section("regression")
    olist = settings.olist
    results_dir = settings.paths.results_dir / "regression"
    fig_dir = settings.paths.figures_dir / "regression"
    results_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, pd.DataFrame] = {}

    if frame is None:
        con = connect(settings.paths.warehouse)
        try:
            set_variables(con, settings)
            candidates = lrm.load_candidates(con)
        finally:
            con.close()
        eligible, tables["population_funnel"] = lrm.build_population(candidates)
        tables["missingness"] = lrm.missingness_table(eligible)
        frame, refs = lrm.prepare_model_frame(
            eligible, int(olist["low_review_max_score"]), int(cfg["top_categories"])
        )
    else:
        refs = lrm.references_for(frame)
    logger.info("Model frame: %d orders, references %s", len(frame), refs)

    tables["delay_by_timing"] = cross_tab(frame)
    specs = lrm.build_specs(refs)
    n_draws, seed = int(cfg["simulation_draws"]), int(cfg["seed"])
    fits, dropped = fit_specs(frame, specs)
    tables["specification_comparison"] = comparison_table(fits, specs, dropped, n_draws, seed)

    coefs = []
    for spec in specs:
        t = tidy(fits[spec.name])
        t.insert(0, "spec", spec.name)
        coefs.append(t)
    coef_all = pd.concat(coefs, ignore_index=True)
    coef_all["label"] = coef_all["term"].map(term_label)
    coef_all["group"] = coef_all["term"].map(term_group)
    tables["coefficients_all_specs"] = coef_all

    # Primary-model diagnostics.
    tables["late_or_by_timing_M3"] = late_or_by_timing(fits["M3"], "late", "timing")
    tables["vif_M3"] = vif_table(fits["M3"])
    tables["vif_M5"] = vif_table(fits["M5"])
    tables["performance"] = pd.DataFrame(
        [{"spec": s.name, **performance(fits[s.name])} for s in specs]
    )
    calib = {name: calibration_table(fits[name]) for name in ("M3", "M5")}
    tables["calibration"] = pd.concat(
        [c.assign(spec=name) for name, c in calib.items()], ignore_index=True
    )
    naive = fit_logit(fits["M3"].formula, fits["M3"].data, cluster=None)
    se = tidy(naive)[["term", "std_err"]].merge(
        tidy(fits["M3"])[["term", "std_err"]], on="term", suffixes=("_model", "_cluster")
    )
    se["ratio_cluster_to_model"] = se["std_err_cluster"] / se["std_err_model"]
    tables["standard_errors_M3"] = se
    tables["influence_M3"] = pd.DataFrame([influence_diagnostics(fits["M3"], frame)])
    tables["marginal_effects_M5"] = covariate_effects(fits["M5"], n_draws, seed)

    # Delay x timing cells.
    cell_fit = fit_logit(lrm.cell_model_formula(refs), frame, cluster="seller")
    fits["CELLS"] = cell_fit
    cell_counts = frame.groupby("cell").size().rename("orders").reset_index()
    cell_pred = average_predictions(
        cell_fit, "cell", list(cell_counts["cell"]), n_draws=n_draws, seed=seed
    )
    tables["cell_predictions"] = cell_pred.merge(cell_counts, left_on="level", right_on="cell")
    cell_coefs = tidy(cell_fit)
    cell_coefs["label"] = cell_coefs["term"].map(term_label)
    tables["coefficients_cell_model"] = cell_coefs

    # Non-regression cross-check: Cochran-Mantel-Haenszel.
    post = frame.query("timing == 'post'")
    tables["cmh_tests"] = pd.DataFrame(
        [
            {"population": "Full eligible sample", **cmh_test(frame, "timing")},
            {"population": "Survey after delivery", **cmh_test(post, "region")},
            {"population": "Survey after delivery", **cmh_test(post, "month")},
        ]
    )

    for name, df in tables.items():
        df.to_csv(results_dir / f"{name}.csv", index=False)

    severe = frame[frame["delay_cat"] == "late_8_plus"]
    severe_pre = int((severe["timing"] == "pre").sum())
    m3 = coef_all[coef_all["spec"] == "M3"]
    m5 = coef_all[coef_all["spec"] == "M5"]
    n3, n5 = fits["M3"].nobs, fits["M5"].nobs
    figures = [
        chart_coefficients(
            m3,
            "Adjusted associations with a low review, full eligible sample (M3)",
            f"n={n3:,}. 'Late delivery' = orders surveyed after delivery; timing terms = on-time"
            " orders. Month effects not shown. Grey = CI includes 1.",
            fig_dir / "01_coefficients_M3.png",
        ),
        chart_coefficients(
            m5,
            "Adjusted associations with a low review, post-delivery surveys (M5)",
            f"n={n5:,} orders whose survey was sent after the delivery date. Month effects"
            " included, not shown. Grey = CI includes 1.",
            fig_dir / "02_coefficients_M5.png",
        ),
        chart_spec_comparison(
            tables["specification_comparison"], fig_dir / "03_specification_comparison.png"
        ),
        chart_cells(
            cell_pred,
            cell_counts,
            f"{severe_pre:,} of {len(severe):,} orders 8+ days late had their survey sent"
            " before delivery",
            fig_dir / "04_delay_timing_cells.png",
        ),
        chart_calibration(calib, fig_dir / "05_calibration.png"),
    ]

    numbers = key_numbers(tables, fits)
    (results_dir / "key_numbers.json").write_text(json.dumps(numbers, indent=2))
    logger.info("Wrote %d tables and %d charts", len(tables), len(figures))
    return RegressionResult(frame, refs, fits, tables, figures, numbers)


def key_numbers(tables: dict[str, pd.DataFrame], fits: dict[str, LogitFit]) -> dict:
    comp = tables["specification_comparison"].set_index("spec")

    def spec(name: str) -> dict:
        r = comp.loc[name]
        return {
            "n": int(r["n"]),
            "late_or": float(r["late_or"]),
            "late_or_ci": [float(r["late_or_ci_low"]), float(r["late_or_ci_high"])],
            "late_ame_pp": float(r["late_ame_pp"]),
            "late_ame_ci_pp": [float(r["late_ame_ci_low_pp"]), float(r["late_ame_ci_high_pp"])],
            "auc": float(r["auc"]),
        }

    return {
        "specs": {name: spec(name) for name in comp.index},
        "max_vif_M3": float(tables["vif_M3"]["vif"].max()),
        "max_vif_M5": float(tables["vif_M5"]["vif"].max()),
        "eligible_orders": int(fits["M3"].nobs),
    }
