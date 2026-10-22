"""Python-vs-SQL metric consistency.

The pandas implementation reads the raw fixture CSVs; the SQL implementation reads the
marts built from the same CSVs. Expected values were computed by hand from
tests/fixtures/olist_fixture.py.
"""

from __future__ import annotations

import pytest

from marketplace_analytics.metrics.independent import compute_reference_metrics, load_sources
from marketplace_analytics.metrics.reconcile import reconcile
from marketplace_analytics.metrics.sql_metrics import compute_sql_metrics

HAND_COMPUTED = {
    "orders_total": 4,
    "orders_status_delivered": 2,
    "orders_status_canceled": 1,
    "orders_status_shipped": 1,
    "orders_with_items": 3,
    "orders_with_payments": 3,
    "items_value_cents": 43000,  # 100 + 50 + 200 + 80
    "freight_value_cents": 4750,  # 10 + 5 + 20 + 12.50
    "payment_value_cents": 47750,
    "payment_value_cents_voucher": 6500,
    "payment_value_cents_orders_without_items": 0,
    "payment_diff_nonzero_orders": 0,
    "orders_in_window": 3,  # o3 is in 2018-09
    "delivered_orders_in_window": 2,
    "aov_gross_delivered_window": 192.5,  # (165 + 220) / 2
    "measurable_deliveries_window": 2,
    "late_deliveries_window": 1,
    "late_rate_window": 0.5,
    "reviewed_orders": 3,
    "low_review_orders": 2,  # o1 latest review = 1, o4 = 2
    "review_score_1_orders": 1,
    "review_score_5_orders": 0,  # o1's earlier 5-star review is superseded
    "low_review_rate_late": 0.0,  # o2: late, score 4
    "low_review_rate_on_time": 1.0,  # o1: on time, score 1
    "survey_sent_before_delivery_orders": 0,
}


@pytest.fixture(scope="module")
def python_metrics(built_fixture_warehouse):
    s = built_fixture_warehouse
    o = s.olist
    sources = load_sources(s.paths.raw_dir)
    return compute_reference_metrics(
        sources, o["analysis_start"], o["analysis_end"], o["low_review_max_score"]
    )


@pytest.mark.parametrize(("name", "expected"), HAND_COMPUTED.items())
def test_python_metrics_match_hand_computed_values(python_metrics, name, expected):
    assert python_metrics[name] == pytest.approx(expected)


def test_python_and_sql_metrics_reconcile_on_fixture(python_metrics, fixture_ro_con):
    result = reconcile(python_metrics, compute_sql_metrics(fixture_ro_con))
    assert result["match"].all(), result[~result["match"]].to_string()
    assert len(result) == len(python_metrics)


def test_reconcile_flags_differences_and_missing_metrics():
    result = reconcile(
        {"count": 10, "rate": 0.25, "only_python": 1},
        {"count": 11, "rate": 0.25 + 1e-15, "only_sql": 2},
    ).set_index("metric")
    assert not result.loc["count", "match"]
    assert result.loc["count", "difference"] == 1
    assert result.loc["rate", "match"]  # float noise tolerated
    assert not result.loc["only_python", "match"]
    assert not result.loc["only_sql", "match"]


def test_sql_change_is_caught_by_reconciliation(python_metrics, fixture_con):
    """If a mart value drifts, reconciliation must fail rather than pass silently."""
    fixture_con.execute("UPDATE olist.fct_orders SET is_late = NOT is_late WHERE order_id = 'o1'")
    result = reconcile(python_metrics, compute_sql_metrics(fixture_con)).set_index("metric")
    assert not result.loc["late_deliveries_window", "match"]
