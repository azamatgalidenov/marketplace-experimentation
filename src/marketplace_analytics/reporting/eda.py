"""Historical exploratory analysis of the real Olist data.

Every table is computed by a SQL file in ``sql/analysis`` against the ``olist`` marts;
Python adds uncertainty (Wilson / Newcombe intervals), draws the charts and writes the
outputs. Key metrics are additionally recomputed from the raw CSVs in pandas and
reconciled against SQL before anything is written.

All findings here are observational descriptions of historical data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from matplotlib.ticker import MultipleLocator

from marketplace_analytics.config import SQL_DIR, Settings
from marketplace_analytics.data.warehouse import connect, set_variables
from marketplace_analytics.metrics.independent import compute_reference_metrics, load_sources
from marketplace_analytics.metrics.reconcile import reconcile
from marketplace_analytics.metrics.sql_metrics import compute_sql_metrics
from marketplace_analytics.reporting import style
from marketplace_analytics.statistics.proportions import two_proportion_test, wilson_ci

logger = logging.getLogger(__name__)

ANALYSIS_SQL_DIR = SQL_DIR / "analysis"


class ReconciliationError(RuntimeError):
    """Raised when Python and SQL metric implementations disagree."""


@dataclass
class EdaResult:
    reconciliation: pd.DataFrame
    tables: dict[str, pd.DataFrame]
    figures: list[Path] = field(default_factory=list)
    key_numbers: dict[str, float] = field(default_factory=dict)


def _ratio(numerator: float, denominator: float) -> float:
    """Division that returns NaN (not a warning) when the population is empty."""
    return float(numerator) / float(denominator) if denominator else float("nan")


def run_analysis_queries(
    con: duckdb.DuckDBPyConnection, sql_dir: Path = ANALYSIS_SQL_DIR
) -> dict[str, pd.DataFrame]:
    tables = {}
    for path in sorted(sql_dir.glob("*.sql")):
        tables[path.stem] = con.execute(path.read_text(encoding="utf-8")).df()
    return tables


def add_wilson(df: pd.DataFrame, successes: str, n: str, prefix: str) -> pd.DataFrame:
    """Append rate and 95% Wilson interval columns for successes / n."""
    out = df.copy()
    bounds = [wilson_ci(int(x), int(k)) for x, k in zip(out[successes], out[n], strict=True)]
    out[f"{prefix}_rate"] = out[successes] / out[n]
    out[f"{prefix}_ci_low"] = [b[0] for b in bounds]
    out[f"{prefix}_ci_high"] = [b[1] for b in bounds]
    return out


def late_vs_on_time_review(survey_table: pd.DataFrame) -> pd.DataFrame:
    """Low-review rate, late vs on-time, overall and excluding pre-delivery surveys.

    Rows of ``survey_table`` come from inv_late_review_by_survey_timing.sql.
    """
    t = survey_table.copy()
    populations = {
        "All measurable reviewed deliveries": t,
        "Survey sent on/after delivery date": t[t["survey_sent_before_delivery"] == False],  # noqa: E712
    }
    rows = []
    for label, sub in populations.items():
        late = sub[sub["is_late"] == True]  # noqa: E712
        on_time = sub[sub["is_late"] == False]  # noqa: E712
        x1, n1 = int(late["low_reviews"].sum()), int(late["reviewed_orders"].sum())
        x2, n2 = int(on_time["low_reviews"].sum()), int(on_time["reviewed_orders"].sum())
        res = two_proportion_test(x1, n1, x2, n2)
        rows.append(
            {
                "population": label,
                "late_reviewed": n1,
                "late_low_reviews": x1,
                "late_low_rate": res.p1,
                "on_time_reviewed": n2,
                "on_time_low_reviews": x2,
                "on_time_low_rate": res.p2,
                "difference_pp": res.difference,
                "diff_ci_low": res.ci_low,
                "diff_ci_high": res.ci_high,
                "risk_ratio": res.p1 / res.p2,
                "z": res.z,
                "p_value": res.p_value,
            }
        )
    return pd.DataFrame(rows)


def enrich(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    t = dict(tables)
    t["eda_delivery_monthly"] = add_wilson(
        t["eda_delivery_monthly"], "late_orders", "measurable_orders", "late"
    )
    t["eda_review_by_delay"] = add_wilson(
        t["eda_review_by_delay"], "low_reviews", "reviewed_orders", "low_review"
    )
    t["eda_regions"] = add_wilson(
        add_wilson(t["eda_regions"], "late_orders", "orders", "late"),
        "low_reviews",
        "reviewed_orders",
        "low_review",
    )
    cats = t["eda_categories"].dropna(subset=["reviewed_orders"])
    cats = cats[cats["reviewed_orders"] > 0]
    t["eda_categories"] = t["eda_categories"].merge(
        add_wilson(cats, "low_reviews", "reviewed_orders", "low_review")[
            ["category_name", "low_review_ci_low", "low_review_ci_high"]
        ],
        on="category_name",
        how="left",
    )
    t["inv_late_vs_on_time_review"] = late_vs_on_time_review(t["inv_late_review_by_survey_timing"])
    return t


def _month_axis(ax, months: pd.Series) -> None:
    ticks = list(range(0, len(months), 3))
    ax.set_xticks(ticks)
    ax.set_xticklabels([pd.Timestamp(months.iloc[i]).strftime("%b\n%Y") for i in ticks])


def chart_monthly_orders(df: pd.DataFrame, path: Path) -> Path:
    fig, ax = style.new_figure()
    x = np.arange(len(df))
    ax.bar(x, df["orders"], color=style.BLUE, width=0.75)
    peak = int(df["orders"].idxmax())
    ax.annotate(
        f"{df['orders'].iloc[peak]:,} orders",
        (peak, df["orders"].iloc[peak]),
        xytext=(0, 4),
        textcoords="offset points",
        ha="center",
        fontsize=9,
        color=style.TEXT_PRIMARY,
    )
    _month_axis(ax, df["purchase_month"])
    style.thousands_axis(ax)
    ax.set_ylabel("Orders (all statuses)")
    ax.grid(axis="x", visible=False)
    style.finish(
        fig,
        "Monthly order volume",
        "Orders per purchase month, all statuses, Jan 2017 - Aug 2018",
    )
    return style.save(fig, path)


def chart_monthly_value(df: pd.DataFrame, path: Path) -> Path:
    fig, (a1, a2) = style.new_figure(ncols=2, width=11)
    x = np.arange(len(df))
    a1.plot(x, df["delivered_gross_value"], color=style.BLUE)
    a1.set_title("Gross order value (items + freight), BRL")
    style.thousands_axis(a1, prefix="R$")
    a2.plot(x, df["delivered_aov"], color=style.BLUE)
    a2.set_title("Average order value (gross), BRL")
    a2.set_ylim(0, df["delivered_aov"].max() * 1.2)
    for ax in (a1, a2):
        _month_axis(ax, df["purchase_month"])
        ax.set_ylim(bottom=0)
    style.finish(
        fig,
        "Monthly gross order value and average order value",
        "Delivered orders by purchase month. Gross customer payments, not platform revenue.",
    )
    return style.save(fig, path)


def chart_order_status(df: pd.DataFrame, path: Path) -> Path:
    delivered = df[df["order_status"] == "delivered"]
    d = df[df["order_status"] != "delivered"].sort_values("orders")
    fig, ax = style.new_figure(height=4.2)
    ax.barh(d["order_status"], d["orders"], color=style.BLUE, height=0.6)
    for y, (n, s) in enumerate(zip(d["orders"], d["share"], strict=True)):
        ax.text(n, y, f"  {n:,} ({s:.1%})", va="center", fontsize=9, color=style.TEXT_PRIMARY)
    ax.set_xlim(0, d["orders"].max() * 1.25)
    ax.set_xlabel("Orders")
    ax.grid(axis="y", visible=False)
    n_del, s_del = int(delivered["orders"].sum()), float(delivered["share"].sum())
    style.finish(
        fig,
        f"{s_del:.1%} of orders in the window have status 'delivered'",
        f"Orders not delivered, by current status, Jan 2017 - Aug 2018"
        f" (delivered: {n_del:,}, not shown). Share = of all orders in the window.",
    )
    return style.save(fig, path)


def chart_payment_mix(mix: pd.DataFrame, inst: pd.DataFrame, path: Path) -> Path:
    fig, (a1, a2) = style.new_figure(ncols=2, width=11)
    d = mix.sort_values("value_share")
    a1.barh(d["payment_type"], d["value_share"], color=style.BLUE, height=0.6)
    for y, v in enumerate(d["value_share"]):
        a1.text(v, y, f"  {v:.1%}", va="center", fontsize=9, color=style.TEXT_PRIMARY)
    style.pct_axis(a1, "x")
    a1.set_xlim(0, 1)
    a1.set_title("Share of payment value by method")
    a1.grid(axis="y", visible=False)
    i = inst[inst["payment_installments"] >= 1]
    a2.bar(i["payment_installments"], i["share"], color=style.BLUE, width=0.75)
    style.pct_axis(a2)
    a2.set_xlabel("Number of instalments")
    a2.set_title("Credit-card payments by instalments")
    a2.grid(axis="x", visible=False)
    style.finish(
        fig,
        "Payment value by method and credit-card instalments",
        "Payment records, all statuses, Jan 2017 - Aug 2018",
    )
    return style.save(fig, path)


def chart_delay_histogram(df: pd.DataFrame, path: Path) -> Path:
    d = df[(df["delivery_delay_days"] >= -40) & (df["delivery_delay_days"] <= 30)]
    clipped = int(df["orders"].sum() - d["orders"].sum())
    fig, ax = style.new_figure()
    colors = [style.ORANGE if v > 0 else style.BLUE for v in d["delivery_delay_days"]]
    ax.bar(d["delivery_delay_days"], d["orders"], color=colors, width=0.85)
    ax.axvline(0.5, color=style.TEXT_SECONDARY, linewidth=1, linestyle="--")
    ax.text(1.5, ax.get_ylim()[1] * 0.9, "Late (after promised date)", color=style.TEXT_PRIMARY)
    ax.text(-1.5, ax.get_ylim()[1] * 0.9, "On time or early", ha="right", color=style.TEXT_PRIMARY)
    ax.set_xlabel("Delivery date minus promised date (days)")
    ax.set_ylabel("Orders")
    style.thousands_axis(ax)
    ax.grid(axis="x", visible=False)
    early_share = float(df.loc[df["delivery_delay_days"] < 0, "orders"].sum() / df["orders"].sum())
    style.finish(
        fig,
        f"{early_share:.0%} of measurable orders arrived before the promised date",
        f"Measurable deliveries, Jan 2017 - Aug 2018; {clipped:,} orders outside -40..+30 days"
        " not shown",
    )
    return style.save(fig, path)


def chart_late_rate_monthly(df: pd.DataFrame, path: Path) -> Path:
    fig, ax = style.new_figure()
    x = np.arange(len(df))
    ax.fill_between(
        x,
        df["late_ci_low"],
        df["late_ci_high"],
        color=style.BLUE,
        alpha=0.18,
        linewidth=0,
        label="95% CI",
    )
    ax.plot(x, df["late_rate"], color=style.BLUE, marker="o", markersize=4, label="Late rate")
    _month_axis(ax, df["purchase_month"])
    style.pct_axis(ax)
    ax.yaxis.set_major_locator(MultipleLocator(0.02))
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Share delivered after promised date")
    ax.legend(loc="upper left")
    top = df.nlargest(3, "late_rate").sort_values("purchase_month")
    peaks = ", ".join(
        f"{pd.Timestamp(m):%b %Y} ({r:.0%})"
        for m, r in zip(top["purchase_month"], top["late_rate"], strict=True)
    )
    style.finish(
        fig,
        f"Highest late-delivery months: {peaks}",
        "Late-delivery rate by purchase month, measurable deliveries (Wilson 95% intervals)",
    )
    return style.save(fig, path)


def chart_review_distribution(df: pd.DataFrame, path: Path) -> Path:
    d = df.dropna(subset=["review_score"])
    fig, ax = style.new_figure(height=4.2)
    colors = [style.ORANGE if s <= 2 else style.BLUE for s in d["review_score"]]
    ax.bar(d["review_score"].astype(int), d["share_of_reviewed"], color=colors, width=0.6)
    for s, v in zip(d["review_score"].astype(int), d["share_of_reviewed"], strict=True):
        ax.text(s, v, f"{v:.1%}", ha="center", va="bottom", fontsize=9, color=style.TEXT_PRIMARY)
    style.pct_axis(ax)
    ax.set_xlabel("Review score (latest review per order)")
    ax.grid(axis="x", visible=False)
    n_missing = int(df.loc[df["review_score"].isna(), "orders"].sum())
    share = dict(zip(d["review_score"].astype(int), d["share_of_reviewed"], strict=True))
    style.finish(
        fig,
        f"{share.get(5, 0):.0%} of reviewed orders score 5; {share.get(1, 0):.0%} score 1",
        f"Share of reviewed orders, Jan 2017 - Aug 2018; scores 1-2 (orange) count as low."
        f" {n_missing:,} orders without a review excluded",
    )
    return style.save(fig, path)


def chart_review_by_delay(df: pd.DataFrame, path: Path) -> Path:
    fig, ax = style.new_figure()
    x = np.arange(len(df))
    colors = [style.ORANGE if "late" in b else style.BLUE for b in df["delay_bucket"]]
    err = [
        df["low_review_rate"] - df["low_review_ci_low"],
        df["low_review_ci_high"] - df["low_review_rate"],
    ]
    ax.bar(x, df["low_review_rate"], color=colors, width=0.65)
    ax.errorbar(
        x,
        df["low_review_rate"],
        yerr=err,
        fmt="none",
        ecolor=style.TEXT_PRIMARY,
        capsize=3,
        linewidth=1,
    )
    for xi, (r, n) in enumerate(zip(df["low_review_rate"], df["reviewed_orders"], strict=True)):
        ax.text(
            xi, r + 0.03, f"{r:.0%}\nn={n:,}", ha="center", fontsize=8, color=style.TEXT_PRIMARY
        )
    ax.set_xticks(x)
    ax.set_xticklabels(df["delay_bucket"].str.replace(" days ", "\ndays "), fontsize=8.5)
    style.pct_axis(ax)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Share of reviews scoring 1-2")
    ax.grid(axis="x", visible=False)
    style.finish(
        fig,
        "Low-review rate by delivery delay (observational)",
        "Low-review rate by delivery delay, measurable reviewed deliveries (95% Wilson CIs)."
        " Association, not a causal estimate.",
    )
    return style.save(fig, path)


def chart_categories(df: pd.DataFrame, path: Path, top: int = 15) -> Path:
    d = df.head(top).iloc[::-1]
    fig, (a1, a2) = style.new_figure(ncols=2, width=11, height=5.6, sharey=True)
    a1.barh(d["category_name"], d["gmv"], color=style.BLUE, height=0.6)
    style.thousands_axis(a1, "x", prefix="R$")
    a1.set_title("Merchandise value (item prices)")
    a1.grid(axis="y", visible=False)
    y = np.arange(len(d))
    err = [
        d["low_review_rate"] - d["low_review_ci_low"],
        d["low_review_ci_high"] - d["low_review_rate"],
    ]
    a2.errorbar(
        d["low_review_rate"],
        y,
        xerr=err,
        fmt="o",
        color=style.BLUE,
        ecolor=style.TEXT_SECONDARY,
        capsize=2,
        markersize=5,
    )
    style.pct_axis(a2, "x")
    a2.set_title("Low-review rate (95% CI)")
    a2.grid(axis="y", visible=False)
    style.finish(
        fig,
        f"Top {top} categories by merchandise value",
        "Jan 2017 - Aug 2018. Value: item prices of delivered orders. Review rate: measurable"
        " deliveries by the order's primary category (each order counted once).",
    )
    return style.save(fig, path)


def chart_regions(df: pd.DataFrame, path: Path) -> Path:
    d = df.sort_values("orders")
    fig, axes = style.new_figure(ncols=4, width=13, height=4, sharey=True)
    panels = [
        ("orders", "Orders", None),
        ("aov_gross", "Average order value (BRL)", None),
        ("median_delivery_days", "Median delivery time (days)", None),
        ("late_rate", "Late-delivery rate", "pct"),
    ]
    for ax, (col, title, kind) in zip(axes, panels, strict=True):
        ax.barh(d["customer_region"], d[col], color=style.BLUE, height=0.6)
        for yi, v in enumerate(d[col]):
            label = f"{v:.1%}" if kind == "pct" else (f"{v:,.0f}" if v >= 100 else f"{v:.1f}")
            ax.text(v, yi, f" {label}", va="center", fontsize=8.5, color=style.TEXT_PRIMARY)
        ax.set_title(title, fontsize=10)
        ax.set_xlim(0, d[col].max() * 1.35)
        ax.set_xticks([])
        ax.grid(False)
    slowest = d.loc[d["median_delivery_days"].idxmax()]
    latest = d.loc[d["late_rate"].idxmax()]
    style.finish(
        fig,
        f"Slowest median delivery: {slowest['customer_region']}; highest late rate:"
        f" {latest['customer_region']}",
        "Measurable deliveries by customer macro-region (IBGE), Jan 2017 - Aug 2018",
    )
    return style.save(fig, path)


def chart_survey_timing(df: pd.DataFrame, path: Path) -> Path:
    before = df[df["days_from_delivery"] < 0]
    after = df[df["days_from_delivery"] >= 0]
    shown = before[before["days_from_delivery"] >= -30]
    hidden = int(before["reviewed_orders"].sum() - shown["reviewed_orders"].sum())
    on_time = shown["reviewed_orders"] - shown["late_orders"]
    fig, ax = style.new_figure()
    ax.bar(
        shown["days_from_delivery"],
        shown["late_orders"],
        color=style.ORANGE,
        width=0.85,
        label="Late order",
    )
    ax.bar(
        shown["days_from_delivery"],
        on_time,
        bottom=shown["late_orders"],
        color=style.BLUE,
        width=0.85,
        label="On-time order",
    )
    ax.set_xlabel("Survey-sent date minus delivery date (days)")
    ax.set_ylabel("Reviewed orders")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    late_share = _ratio(before["late_orders"].sum(), before["reviewed_orders"].sum())
    style.finish(
        fig,
        f"{late_share:.0%} of surveys sent before delivery belong to late orders",
        f"{int(before['reviewed_orders'].sum()):,} surveys sent before delivery ({hidden:,}"
        f" earlier than -30 days not shown); {int(after['reviewed_orders'].sum()):,} sent"
        " on/after delivery excluded",
    )
    return style.save(fig, path)


def make_charts(t: dict[str, pd.DataFrame], fig_dir: Path) -> list[Path]:
    return [
        chart_monthly_orders(t["eda_monthly_orders"], fig_dir / "01_monthly_orders.png"),
        chart_monthly_value(t["eda_monthly_orders"], fig_dir / "02_monthly_value_aov.png"),
        chart_order_status(t["eda_order_status"], fig_dir / "03_order_status.png"),
        chart_payment_mix(
            t["eda_payment_mix"], t["eda_installments"], fig_dir / "04_payment_mix.png"
        ),
        chart_delay_histogram(t["eda_delivery_delay"], fig_dir / "05_delivery_delay.png"),
        chart_late_rate_monthly(t["eda_delivery_monthly"], fig_dir / "06_late_rate_monthly.png"),
        chart_review_distribution(
            t["eda_review_distribution"], fig_dir / "07_review_distribution.png"
        ),
        chart_review_by_delay(t["eda_review_by_delay"], fig_dir / "08_low_review_by_delay.png"),
        chart_categories(t["eda_categories"], fig_dir / "09_categories.png"),
        chart_regions(t["eda_regions"], fig_dir / "10_regions.png"),
        chart_survey_timing(t["inv_survey_lag"], fig_dir / "11_survey_timing.png"),
    ]


PAYMENT_DIFF_CLASSES = [
    "1: exact match",
    "2: 1 cent apart",
    "3: paid more than items + freight",
    "4: paid less than items + freight",
]


def key_numbers(t: dict[str, pd.DataFrame], recon_metrics: dict[str, float]) -> dict:
    v = t["eda_value_summary"].iloc[0]
    lvr = t["inv_late_vs_on_time_review"].set_index("population")
    pop = t["inv_delivery_population"].set_index("step")
    survey = t["inv_survey_timing"]
    before = survey[survey["survey_sent_before_delivery"] == True]  # noqa: E712
    pay = (
        t["inv_payment_differences"]
        .set_index("difference_class")["orders"]
        .reindex(PAYMENT_DIFF_CLASSES, fill_value=0)
    )
    return {
        "orders_in_window": int(v["orders"]),
        "delivered_orders_in_window": int(v["delivered_orders"]),
        "delivered_gmv": float(v["delivered_gmv"]),
        "delivered_gross_value": float(v["delivered_gross_value"]),
        "payment_value_all_statuses_window": float(v["payment_value_all_statuses"]),
        "aov_gross_delivered": float(v["aov_gross_delivered"]),
        "median_gross_delivered": float(v["median_gross_delivered"]),
        "late_rate_headline": float(pop.loc[4, "late_rate_date_level"]),
        "late_rate_timestamp_definition": float(pop.loc[4, "late_rate_timestamp_level"]),
        "measurable_deliveries_window": int(pop.loc[4, "orders"]),
        "low_review_rate_late": float(lvr.iloc[0]["late_low_rate"]),
        "low_review_rate_on_time": float(lvr.iloc[0]["on_time_low_rate"]),
        "survey_before_delivery_orders": int(before["reviewed_orders"].sum()),
        "survey_before_delivery_low_rate": _ratio(
            before["low_reviews"].sum(), before["reviewed_orders"].sum()
        ),
        "survey_before_delivery_late_share": _ratio(
            before.loc[before["is_late"] == True, "reviewed_orders"].sum(),  # noqa: E712
            before["reviewed_orders"].sum(),
        ),
        "payment_orders_exact": int(pay.iloc[0]),
        "payment_orders_1_cent": int(pay.iloc[1]),
        "payment_orders_over": int(pay.iloc[2]),
        "payment_orders_under": int(pay.iloc[3]),
        "payment_value_orders_without_items_all_time": recon_metrics[
            "payment_value_cents_orders_without_items"
        ]
        / 100,
    }


def run_eda(settings: Settings, raw_dir: Path | None = None) -> EdaResult:
    raw_dir = raw_dir or settings.paths.raw_dir
    olist = settings.olist
    results_dir = settings.paths.results_dir / "eda"
    fig_dir = settings.paths.figures_dir / "eda"
    results_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Recomputing key metrics independently from raw CSVs in %s", raw_dir)
    py_metrics = compute_reference_metrics(
        load_sources(raw_dir),
        olist["analysis_start"],
        olist["analysis_end"],
        int(olist["low_review_max_score"]),
    )
    con = connect(settings.paths.warehouse)
    try:
        set_variables(con, settings)
        recon = reconcile(py_metrics, compute_sql_metrics(con))
        recon.to_csv(results_dir / "reconciliation_python_vs_sql.csv", index=False)
        mismatches = recon[~recon["match"]]
        if not mismatches.empty:
            raise ReconciliationError(
                "Python and SQL metrics disagree:\n" + mismatches.to_string(index=False)
            )
        logger.info("Reconciliation passed: %d/%d metrics match", len(recon), len(recon))

        tables = enrich(run_analysis_queries(con))
    finally:
        con.close()

    for name, df in tables.items():
        df.to_csv(results_dir / f"{name}.csv", index=False)
    figures = make_charts(tables, fig_dir)
    numbers = key_numbers(tables, py_metrics)
    (results_dir / "key_numbers.json").write_text(json.dumps(numbers, indent=2))
    logger.info(
        "Wrote %d tables to %s and %d charts to %s", len(tables), results_dir, len(figures), fig_dir
    )
    return EdaResult(recon, tables, figures, numbers)
