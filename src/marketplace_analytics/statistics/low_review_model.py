"""Observational model of low review scores on real Olist orders.

Research question: which observable order, delivery, product and geographic factors are
associated with a low review score? Nothing here estimates a causal effect.

Key measurement facts (see reports/eda_findings.md, section 3.3):
* ``review_survey_sent_date`` (source: review_creation_date) is the date the survey was
  sent, at day precision. ``review_answered_at`` is when the customer answered.
* Late orders usually receive the survey before they arrive, so lateness and survey
  timing are entangled. Survey timing is therefore modelled explicitly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import duckdb
import numpy as np
import pandas as pd

from marketplace_analytics.config import SQL_DIR

logger = logging.getLogger(__name__)

CANDIDATES_SQL = SQL_DIR / "models" / "low_review_candidates.sql"

TIMING_LEVELS = ["post", "same_day", "pre"]  # reference first
DELAY_LEVELS = ["on_time", "late_1_3", "late_4_7", "late_8_plus"]
REFERENCE_REGION = "Southeast"


def load_candidates(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(CANDIDATES_SQL.read_text(encoding="utf-8")).df()


def build_population(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply eligibility rules in order and count what each rule removes.

    Returns the eligible rows and a funnel table.
    """
    steps = [
        ("Orders purchased in analysis window", pd.Series(True, index=candidates.index)),
        ("Delivered with a customer-delivery timestamp", candidates["is_delivery_measurable"]),
        ("Has a review (latest review per order)", candidates["review_score"].notna()),
        (
            "Survey sent and answered on/after purchase (drops source inconsistencies)",
            (candidates["review_survey_sent_date"] >= candidates["purchase_date"])
            & (candidates["review_answered_at"] >= candidates["purchased_at"]),
        ),
    ]
    keep = pd.Series(True, index=candidates.index)
    rows = []
    for label, rule in steps:
        before = int(keep.sum())
        keep &= rule.fillna(False).astype(bool)
        rows.append(
            {"step": label, "remaining": int(keep.sum()), "removed": before - int(keep.sum())}
        )
    return candidates.loc[keep].copy(), pd.DataFrame(rows)


def low_review_outcome(score: pd.Series, max_score: int) -> pd.Series:
    """1 if the review score is at or below ``max_score``, else 0. Missing scores raise."""
    if score.isna().any():
        raise ValueError("Outcome requires a review score for every row")
    return (score <= max_score).astype(int)


def classify_survey_timing(
    sent_date: pd.Series,
    delivered_at: pd.Series,
    answered_at: pd.Series | None = None,
    rule: str = "sent_date",
) -> pd.Series:
    """Timing of the satisfaction survey relative to delivery.

    rule="sent_date" (primary): compare the survey-sent calendar date with the delivery
        calendar date -> "pre" (sent before), "same_day", "post" (sent after). Same day
        is kept separate because a date-only field cannot order events within the day.
    rule="answered": compare the customer's ANSWER timestamp with the delivery
        timestamp -> "pre" (answered before the parcel arrived) or "post".
    """
    delivered = pd.to_datetime(delivered_at)
    if delivered.isna().any():
        raise ValueError("Survey timing undefined: missing delivery timestamps")
    if rule == "sent_date":
        sent = pd.to_datetime(sent_date).dt.normalize()
        if sent.isna().any():
            raise ValueError("Survey timing undefined: missing survey-sent dates")
        delivered_date = delivered.dt.normalize()
        timing = np.select(
            [sent < delivered_date, sent == delivered_date], ["pre", "same_day"], default="post"
        )
    elif rule == "answered":
        if answered_at is None:
            raise ValueError("rule='answered' needs answered_at")
        answered = pd.to_datetime(answered_at)
        if answered.isna().any():
            raise ValueError("Survey timing undefined: missing answer timestamps")
        timing = np.where(answered < delivered, "pre", "post")
    else:
        raise ValueError(f"Unknown timing rule: {rule}")
    return pd.Series(timing, index=sent_date.index)


def delay_category(delay_days: pd.Series) -> pd.Series:
    """Days delivered after the promised date: on time (<= 0), 1-3, 4-7, 8+ days late."""
    bins = [-np.inf, 0, 3, 7, np.inf]
    return pd.cut(delay_days, bins=bins, labels=DELAY_LEVELS).astype(str)


def experience_cells(delay: pd.Series, timing: pd.Series, min_cell: int = 50) -> pd.Series:
    """Combine delay category and survey timing into one categorical variable.

    Within a timing group, sparse late categories are merged upwards (8+ into 4-7, giving
    "late_4_plus") when the 8+ cell has fewer than ``min_cell`` orders, so no coefficient
    rests on a near-empty cell.
    """
    delay = delay.copy()
    for t in timing.unique():
        in_t = timing == t
        if (in_t & (delay == "late_8_plus")).sum() < min_cell:
            delay[in_t & delay.isin(["late_4_7", "late_8_plus"])] = "late_4_plus"
    return delay + "|" + timing


def group_categories(category: pd.Series, top_n: int) -> pd.Series:
    """Keep the ``top_n`` most frequent categories; pool the rest as "other".

    "unknown" (products without a category) is kept as its own level, never pooled, so the
    missing-category group stays visible.
    """
    counts = category[category != "unknown"].value_counts()
    keep = set(counts.index[:top_n]) | {"unknown"}
    return category.where(category.isin(keep), "other")


@dataclass(frozen=True)
class References:
    category: str
    month: str
    region: str = REFERENCE_REGION
    timing: str = "post"
    cell: str = "on_time|post"
    basket: str = "single_item"


def prepare_model_frame(
    eligible: pd.DataFrame, low_review_max_score: int, top_categories: int
) -> tuple[pd.DataFrame, References]:
    df = eligible.copy()
    out = pd.DataFrame(index=df.index)
    out["order_id"] = df["order_id"]
    out["seller"] = df["primary_seller_id"]
    out["low_review"] = low_review_outcome(df["review_score"], low_review_max_score)
    out["low_review_le3"] = low_review_outcome(df["review_score"], 3)

    # Lateness: primary = delivery calendar date after the promised date.
    out["late"] = (df["delivery_delay_days"] > 0).astype(int)
    # Sensitivity: delivery timestamp after the promised date at 00:00.
    out["late_ts"] = (
        pd.to_datetime(df["delivered_to_customer_at"])
        > pd.to_datetime(df["estimated_delivery_date"])
    ).astype(int)
    out["delay_cat"] = delay_category(df["delivery_delay_days"])

    out["timing"] = classify_survey_timing(
        df["review_survey_sent_date"], df["delivered_to_customer_at"]
    )
    out["timing_answer"] = classify_survey_timing(
        df["review_survey_sent_date"],
        df["delivered_to_customer_at"],
        df["review_answered_at"],
        rule="answered",
    )
    out["same_day"] = (out["timing"] == "same_day").astype(int)
    out["cell"] = experience_cells(out["delay_cat"], out["timing"])
    # Survey sent before both delivery and the promised date: timing not explained by
    # the "sent once the promise passes" pattern (EDA section 3.3).
    out["unexplained_early_survey"] = (
        (out["timing"] == "pre")
        & (
            pd.to_datetime(df["review_survey_sent_date"])
            < pd.to_datetime(df["estimated_delivery_date"])
        )
    ).astype(int)
    out["single_review"] = (df["review_count"] == 1).astype(int)

    # Order and product covariates (all known before the review).
    out["promised_weeks"] = df["estimated_delivery_days"] / 7
    out["log_items_value"] = np.log(df["items_value"].astype(float))
    out["freight_share_10pp"] = (
        df["freight_value"].astype(float) / df["order_gross_value"].astype(float) * 10
    )
    # Basket structure as one variable: multi-seller orders are always multi-item, so two
    # separate flags would be nested (and imply impossible counterfactuals).
    out["basket"] = np.select(
        [df["distinct_sellers"] > 1, df["item_count"] > 1],
        ["multi_seller", "multi_item_one_seller"],
        default="single_item",
    )
    out["category"] = group_categories(df["primary_category"], top_categories)
    out["region"] = df["customer_region"]
    out["month"] = df["purchase_month"]

    missing = out.isna().sum()
    if missing.any():
        raise ValueError(f"Model frame has missing values:\n{missing[missing > 0]}")
    return out, references_for(out)


def references_for(frame: pd.DataFrame) -> References:
    """Reference levels: the most frequent named category and the most frequent month."""
    named = frame.loc[~frame["category"].isin(["other", "unknown"]), "category"]
    return References(
        category=named.value_counts().index[0],
        month=frame["month"].value_counts().index[0],
    )


def missingness_table(eligible: pd.DataFrame) -> pd.DataFrame:
    """Missing values per source field in the eligible population (before any imputation)."""
    cols = [
        "review_score",
        "review_survey_sent_date",
        "review_answered_at",
        "delivered_to_customer_at",
        "estimated_delivery_date",
        "items_value",
        "freight_value",
        "primary_category",
        "customer_region",
        "primary_seller_id",
    ]
    rows = [
        {"field": c, "missing": int(eligible[c].isna().sum()), "rows": len(eligible)} for c in cols
    ]
    rows.append(
        {
            "field": "primary_category == 'unknown' (product without category)",
            "missing": int((eligible["primary_category"] == "unknown").sum()),
            "rows": len(eligible),
        }
    )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    label: str
    group: str  # "main", "timing sensitivity", "assumption sensitivity"
    formula: str
    sample: str  # pandas query over the model frame; "" = full eligible sample
    late_term: str = "late"
    # Rows over which the late-vs-on-time average marginal effect is averaged.
    ame_population: str = ""
    notes: str = ""
    extra: dict = field(default_factory=dict)


def covariates(refs: References) -> str:
    return (
        "promised_weeks + log_items_value + freight_share_10pp"
        f" + C(basket, Treatment('{refs.basket}'))"
        f" + C(category, Treatment('{refs.category}'))"
        f" + C(region, Treatment('{refs.region}'))"
        f" + C(month, Treatment('{refs.month}'))"
    )


def build_specs(refs: References) -> list[ModelSpec]:
    cov = covariates(refs)
    timing = f"C(timing, Treatment('{refs.timing}'))"
    timing_ans = f"C(timing_answer, Treatment('{refs.timing}'))"
    post_sent = "timing == 'post'"
    return [
        ModelSpec(
            "M1",
            "Simple, full sample",
            "main",
            "low_review ~ late",
            "",
            notes="Unadjusted association; mixes survey timing into 'late'.",
        ),
        ModelSpec(
            "M2",
            "Timing-adjusted, full sample",
            "main",
            f"low_review ~ late * {timing}",
            "",
            ame_population=post_sent,
            notes="'late' = association among surveys sent after the delivery date.",
        ),
        ModelSpec(
            "M3",
            "Adjusted, full sample (primary)",
            "main",
            f"low_review ~ late * {timing} + {cov}",
            "",
            ame_population=post_sent,
            notes="Primary full-sample model.",
        ),
        ModelSpec(
            "M4",
            "Simple, post-delivery surveys",
            "main",
            "low_review ~ late",
            post_sent,
            notes="Restricted to surveys sent after the delivery date.",
        ),
        ModelSpec(
            "M5",
            "Adjusted, post-delivery surveys",
            "main",
            f"low_review ~ late + {cov}",
            post_sent,
            notes="Primary restricted model; late orders here are almost all 1-7 days late.",
        ),
        ModelSpec(
            "T1",
            "Post-delivery incl. same-day surveys",
            "timing sensitivity",
            f"low_review ~ late + {cov}",
            "timing in ['post', 'same_day']",
            notes="Adds surveys sent on the delivery date.",
        ),
        ModelSpec(
            "T2",
            "Answered after delivery",
            "timing sensitivity",
            f"low_review ~ late + {cov}",
            "timing_answer == 'post'",
            notes="Uses the answer timestamp instead of the survey-sent date.",
        ),
        ModelSpec(
            "T3",
            "Full sample, answer-based timing",
            "timing sensitivity",
            f"low_review ~ late * {timing_ans} + {cov}",
            "",
            ame_population="timing_answer == 'post'",
            notes="Timing classified by answer time vs delivery timestamp.",
        ),
        ModelSpec(
            "T4",
            "Full sample excl. unexplained early surveys",
            "timing sensitivity",
            # Without these rows every pre-delivery survey belongs to a late order, so the
            # pre-timing main effect and late x pre are not separately identifiable. Only
            # the identifiable contrasts are kept: 'late' (post), late x same-day, and a
            # pre-delivery level that compares late/pre with late/post.
            f"low_review ~ late + {timing} + late:same_day + {cov}",
            "unexplained_early_survey == 0",
            ame_population=post_sent,
            notes="Drops surveys sent before both delivery and the promised date.",
        ),
        ModelSpec(
            "A1",
            "Lateness at timestamp level",
            "assumption sensitivity",
            f"low_review ~ late_ts * {timing} + {cov}",
            "",
            late_term="late_ts",
            ame_population=post_sent,
            notes="Delivered on the promised day counts as late.",
        ),
        ModelSpec(
            "A2",
            "Outcome: score <= 3",
            "assumption sensitivity",
            f"low_review_le3 ~ late * {timing} + {cov}",
            "",
            ame_population=post_sent,
            notes="Neutral (3) reviews counted as low.",
        ),
        ModelSpec(
            "A3",
            "Orders with a single review",
            "assumption sensitivity",
            f"low_review ~ late * {timing} + {cov}",
            "single_review == 1",
            ame_population=post_sent,
            notes="Avoids the latest-review selection rule.",
        ),
        ModelSpec(
            "A4",
            "Excluding 20 sellers with most late orders",
            "assumption sensitivity",
            f"low_review ~ late * {timing} + {cov}",
            "",
            ame_population=post_sent,
            notes="Drops all orders of the 20 sellers with the most late, post-delivery-survey"
            " orders: does the association hinge on a few sellers?",
            extra={"exclude_top_late_sellers": 20},
        ),
    ]


def cell_model_formula(refs: References) -> str:
    return f"low_review ~ C(cell, Treatment('{refs.cell}')) + {covariates(refs)}"
