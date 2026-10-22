"""The same key metrics as ``independent.py``, computed from the SQL marts."""

from __future__ import annotations

import duckdb

from marketplace_analytics.metrics.independent import PAYMENT_TYPES, STATUSES


def _one(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    value = con.execute(sql).fetchone()[0]
    return 0 if value is None else value


def compute_sql_metrics(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    f = "FROM olist.fct_orders"
    m: dict[str, float] = {"orders_total": _one(con, f"SELECT count(*) {f}")}
    for status in STATUSES:
        m[f"orders_status_{status}"] = _one(
            con, f"SELECT count(*) {f} WHERE order_status = '{status}'"
        )
    m["orders_with_items"] = _one(con, f"SELECT count(*) {f} WHERE has_items")
    m["orders_with_payments"] = _one(con, f"SELECT count(*) {f} WHERE payment_records > 0")
    m["items_value_cents"] = _one(con, f"SELECT CAST(sum(items_value) * 100 AS BIGINT) {f}")
    m["freight_value_cents"] = _one(con, f"SELECT CAST(sum(freight_value) * 100 AS BIGINT) {f}")
    m["payment_value_cents"] = _one(con, f"SELECT CAST(sum(payment_value) * 100 AS BIGINT) {f}")
    m["payment_value_cents_orders_without_items"] = _one(
        con, f"SELECT CAST(sum(payment_value) * 100 AS BIGINT) {f} WHERE NOT has_items"
    )
    for ptype in PAYMENT_TYPES:
        m[f"payment_value_cents_{ptype}"] = _one(
            con,
            "SELECT CAST(sum(payment_value) * 100 AS BIGINT) FROM olist.fct_order_payments "
            f"WHERE payment_type = '{ptype}'",
        )

    diff = "CAST((payment_value - order_gross_value) * 100 AS BIGINT)"
    both = f"{f} WHERE has_items AND payment_records > 0"
    m["payment_compared_orders"] = _one(con, f"SELECT count(*) {both}")
    m["payment_diff_nonzero_orders"] = _one(con, f"SELECT count(*) {both} AND {diff} <> 0")
    m["payment_diff_gt_1_cent_orders"] = _one(con, f"SELECT count(*) {both} AND abs({diff}) > 1")

    m["orders_in_window"] = _one(con, f"SELECT count(*) {f} WHERE in_analysis_window")
    aov = f"{f} WHERE order_status = 'delivered' AND in_analysis_window"
    m["delivered_orders_in_window"] = _one(con, f"SELECT count(*) {aov}")
    m["aov_gross_delivered_window"] = float(_one(con, f"SELECT avg(order_gross_value) {aov}"))

    meas = f"{f} WHERE is_delivery_measurable AND in_analysis_window"
    m["measurable_deliveries_window"] = _one(con, f"SELECT count(*) {meas}")
    m["late_deliveries_window"] = _one(con, f"SELECT count(*) {meas} AND is_late")
    m["late_rate_window"] = m["late_deliveries_window"] / m["measurable_deliveries_window"]

    m["reviewed_orders"] = _one(con, f"SELECT count(review_score) {f}")
    m["low_review_orders"] = _one(con, f"SELECT count(*) {f} WHERE is_low_review")
    m["low_review_rate"] = m["low_review_orders"] / m["reviewed_orders"]
    for k in range(1, 6):
        m[f"review_score_{k}_orders"] = _one(con, f"SELECT count(*) {f} WHERE review_score = {k}")

    rev = f"{meas} AND review_score IS NOT NULL"
    m["low_review_rate_late"] = float(
        _one(con, f"SELECT avg(CAST(is_low_review AS DOUBLE)) {rev} AND is_late")
    )
    m["low_review_rate_on_time"] = float(
        _one(con, f"SELECT avg(CAST(is_low_review AS DOUBLE)) {rev} AND NOT is_late")
    )
    m["survey_sent_before_delivery_orders"] = _one(
        con, f"SELECT count(*) {f} WHERE survey_sent_before_delivery"
    )
    return {k: (int(v) if isinstance(v, int) else float(v)) for k, v in m.items()}
