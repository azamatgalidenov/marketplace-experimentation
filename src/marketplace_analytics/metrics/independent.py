"""Key historical metrics recomputed in pandas, directly from the raw Olist CSVs.

This module does not read the warehouse. It parses the CSVs with pandas'
own reader, re-implements every rule (latest review, lateness, analysis window, ...)
and aggregates from source-level records. Agreement with the SQL marts is therefore
evidence that both implementations are right, not that one copied the other.

Shared assumptions (business definitions both sides must agree on, documented in
docs/data_dictionary.md):
  * Latest review per order = latest answer timestamp, then latest creation date,
    then smallest review_id.
  * Late = customer-delivery calendar date > estimated delivery date.
  * Measurable delivery = status 'delivered' and a customer-delivery timestamp exists.
  * Analysis window = purchase date within [analysis_start, analysis_end].
  * Monetary values compared in integer cents (source values have 2 decimals).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from marketplace_analytics.data.download import OLIST_FILES

STATUSES = (
    "created",
    "approved",
    "invoiced",
    "processing",
    "shipped",
    "delivered",
    "canceled",
    "unavailable",
)
PAYMENT_TYPES = ("credit_card", "boleto", "voucher", "debit_card", "not_defined")


def _cents(series: pd.Series) -> pd.Series:
    return (pd.to_numeric(series) * 100).round().astype("int64")


def load_sources(raw_dir: Path) -> dict[str, pd.DataFrame]:
    """Read the source CSVs needed for the reference metrics."""

    def read(table: str, dates: list[str] | None = None) -> pd.DataFrame:
        df = pd.read_csv(raw_dir / OLIST_FILES[table], dtype=str, keep_default_na=False)
        df = df.replace("", pd.NA)
        for col in dates or []:
            df[col] = pd.to_datetime(df[col])
        return df

    orders = read(
        "orders",
        [
            "order_purchase_timestamp",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
    )
    items = read("order_items")
    items["price_cents"] = _cents(items["price"])
    items["freight_cents"] = _cents(items["freight_value"])
    payments = read("order_payments")
    payments["value_cents"] = _cents(payments["payment_value"])
    reviews = read("order_reviews", ["review_creation_date", "review_answer_timestamp"])
    reviews["review_score"] = reviews["review_score"].astype(int)
    return {"orders": orders, "items": items, "payments": payments, "reviews": reviews}


def latest_reviews(reviews: pd.DataFrame) -> pd.DataFrame:
    ordered = reviews.sort_values(
        ["order_id", "review_answer_timestamp", "review_creation_date", "review_id"],
        ascending=[True, False, False, True],
    )
    return ordered.drop_duplicates("order_id", keep="first").set_index("order_id")


def compute_reference_metrics(
    sources: dict[str, pd.DataFrame],
    analysis_start: str,
    analysis_end: str,
    low_review_max_score: int,
) -> dict[str, float]:
    orders = sources["orders"].set_index("order_id")
    items, payments = sources["items"], sources["payments"]
    review = latest_reviews(sources["reviews"])

    m: dict[str, float] = {"orders_total": len(orders)}
    status_counts = orders["order_status"].str.strip().str.lower().value_counts()
    for status in STATUSES:
        m[f"orders_status_{status}"] = int(status_counts.get(status, 0))

    # Per-order item and payment totals, aggregated from line-level records.
    item_tot = items.groupby("order_id")[["price_cents", "freight_cents"]].sum()
    pay_tot = payments.groupby("order_id")["value_cents"].sum()

    m["orders_with_items"] = len(item_tot)
    m["orders_with_payments"] = len(pay_tot)
    m["items_value_cents"] = int(items["price_cents"].sum())
    m["freight_value_cents"] = int(items["freight_cents"].sum())
    m["payment_value_cents"] = int(payments["value_cents"].sum())
    m["payment_value_cents_orders_without_items"] = int(
        pay_tot[~pay_tot.index.isin(item_tot.index)].sum()
    )
    for ptype in PAYMENT_TYPES:
        m[f"payment_value_cents_{ptype}"] = int(
            payments.loc[payments["payment_type"] == ptype, "value_cents"].sum()
        )

    both = item_tot.join(pay_tot, how="inner")
    diff = both["value_cents"] - both["price_cents"] - both["freight_cents"]
    m["payment_compared_orders"] = len(both)
    m["payment_diff_nonzero_orders"] = int((diff != 0).sum())
    m["payment_diff_gt_1_cent_orders"] = int((diff.abs() > 1).sum())

    # Analysis window and AOV (delivered orders; gross = items + freight).
    purchase_date = orders["order_purchase_timestamp"].dt.normalize()
    in_window = purchase_date.between(pd.Timestamp(analysis_start), pd.Timestamp(analysis_end))
    m["orders_in_window"] = int(in_window.sum())
    delivered = orders["order_status"] == "delivered"
    gross = (item_tot["price_cents"] + item_tot["freight_cents"]).reindex(orders.index)
    aov_orders = gross[delivered & in_window].fillna(0)
    m["delivered_orders_in_window"] = len(aov_orders)
    m["aov_gross_delivered_window"] = aov_orders.mean() / 100

    # Delivery performance (date-level).
    delivered_ts = orders["order_delivered_customer_date"]
    measurable = delivered & delivered_ts.notna()
    late = delivered_ts.dt.normalize() > orders["order_estimated_delivery_date"].dt.normalize()
    m["measurable_deliveries_window"] = int((measurable & in_window).sum())
    m["late_deliveries_window"] = int((measurable & in_window & late).sum())
    m["late_rate_window"] = m["late_deliveries_window"] / m["measurable_deliveries_window"]

    # Reviews (latest review per order).
    score = review["review_score"].reindex(orders.index)
    low = score <= low_review_max_score
    m["reviewed_orders"] = int(score.notna().sum())
    m["low_review_orders"] = int(low.sum())
    m["low_review_rate"] = m["low_review_orders"] / m["reviewed_orders"]
    for k in range(1, 6):
        m[f"review_score_{k}_orders"] = int((score == k).sum())

    pop = measurable & in_window & score.notna()
    m["low_review_rate_late"] = float(low[pop & late].mean())
    m["low_review_rate_on_time"] = float(low[pop & ~late].mean())

    sent = review["review_creation_date"].reindex(orders.index).dt.normalize()
    m["survey_sent_before_delivery_orders"] = int(
        (score.notna() & delivered_ts.notna() & (sent < delivered_ts.dt.normalize())).sum()
    )
    return m
