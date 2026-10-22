"""Integration tests: build the warehouse on the hand-made fixture and check exact values."""

from __future__ import annotations

import pytest

from marketplace_analytics.data.warehouse import DataQualityError, run_quality_checks


def _orders(con):
    df = con.execute("SELECT * FROM olist.fct_orders ORDER BY order_id").df()
    return df.set_index("order_id")


def test_all_quality_checks_pass_on_fixture(fixture_ro_con):
    results = run_quality_checks(fixture_ro_con, prefix="olist_")
    assert results, "no quality checks were discovered"
    assert all(r.passed for r in results), [r for r in results if not r.passed]


def test_fct_orders_has_one_row_per_order(fixture_ro_con):
    orders = _orders(fixture_ro_con)
    assert list(orders.index) == ["o1", "o2", "o3", "o4"]


def test_order_values_are_not_inflated_by_joins(fixture_ro_con):
    o = _orders(fixture_ro_con)
    # o1 has 2 items x 2 payments x 2 reviews; a naive join would multiply these.
    assert float(o.loc["o1", "items_value"]) == 150.00
    assert float(o.loc["o1", "freight_value"]) == 15.00
    assert float(o.loc["o1", "order_gross_value"]) == 165.00
    assert float(o.loc["o1", "payment_value"]) == 165.00
    assert o.loc["o1", "item_count"] == 2
    assert float(o["payment_value"].sum()) == 477.50


def test_order_without_items_or_payments(fixture_ro_con):
    o = _orders(fixture_ro_con)
    assert not o.loc["o3", "has_items"]
    assert o.loc["o3", "item_count"] == 0
    assert float(o.loc["o3", "payment_value"]) == 0
    assert o.loc["o3", "primary_payment_type"] is None or o["primary_payment_type"].isna()["o3"]
    assert not o.loc["o3", "in_analysis_window"]


def test_primary_category_and_payment(fixture_ro_con):
    o = _orders(fixture_ro_con)
    assert o.loc["o1", "primary_category"] == "bed_bath_table"  # most expensive line
    assert o.loc["o1", "primary_payment_type"] == "credit_card"  # 100 > 65 voucher
    assert o.loc["o1", "used_voucher"]
    assert o.loc["o1", "max_installments"] == 3
    assert o.loc["o4", "primary_category"] == "unknown"  # product without a category


def test_untranslated_category_keeps_portuguese_name(fixture_ro_con):
    names = fixture_ro_con.execute(
        "SELECT category_name FROM olist.dim_product WHERE product_id = 'p2'"
    ).fetchone()
    assert names == ("pc_gamer",)


def test_latest_review_wins_and_review_id_reuse_is_kept(fixture_ro_con):
    o = _orders(fixture_ro_con)
    assert o.loc["o1", "review_score"] == 1
    assert o.loc["o1", "review_count"] == 2
    assert o.loc["o1", "is_low_review"]
    assert o.loc["o1", "review_has_comment"]
    assert o.loc["o2", "review_score"] == 4  # same review_id r1, different order
    assert o.isna().loc["o3", "review_score"]


def test_delivery_metrics(fixture_ro_con):
    o = _orders(fixture_ro_con)
    assert o.loc["o1", "delivery_delay_days"] == -2
    assert not o.loc["o1", "is_late"]
    assert o.loc["o2", "delivery_delay_days"] == 5
    assert o.loc["o2", "is_late"]
    assert o.loc["o1", "delivery_days"] == pytest.approx(7.0)
    assert o.loc["o1", "is_delivery_measurable"]
    assert not o.loc["o4", "is_delivery_measurable"]  # shipped, not delivered


def test_repeat_purchase_uses_customer_unique_id(fixture_ro_con):
    o = _orders(fixture_ro_con)
    assert not o.loc["o1", "is_repeat_purchase"]
    assert o.loc["o2", "is_repeat_purchase"]
    assert o.loc["o2", "customer_region"] == "Southeast"
    assert o.loc["o4", "customer_region"] == "Northeast"


def test_dim_date_covers_all_purchase_months(fixture_ro_con):
    first, last, n = fixture_ro_con.execute(
        "SELECT min(date), max(date), count(*) FROM olist.dim_date"
    ).fetchone()
    assert str(first) == "2017-03-01"
    assert str(last) == "2018-09-30"
    assert n == (last - first).days + 1


# Negative tests: each check catches the defect it targets.


def _failed(results):
    return {r.name for r in results if not r.passed}


def test_duplicate_order_is_detected(fixture_con):
    fixture_con.execute(
        "INSERT INTO olist.fct_orders SELECT * FROM olist.fct_orders WHERE order_id = 'o1'"
    )
    results = run_quality_checks(fixture_con, prefix="olist_", raise_on_error=False)
    assert {"olist_unique_grain", "olist_reconcile_totals"} <= _failed(results)
    with pytest.raises(DataQualityError):
        run_quality_checks(fixture_con, prefix="olist_")


def test_fanned_out_value_is_detected(fixture_con):
    fixture_con.execute(
        "UPDATE olist.fct_orders SET payment_value = payment_value * 2 WHERE order_id = 'o1'"
    )
    results = run_quality_checks(fixture_con, prefix="olist_", raise_on_error=False)
    assert "olist_reconcile_totals" in _failed(results)


def test_orphan_and_invalid_values_are_detected(fixture_con):
    fixture_con.execute(
        "UPDATE olist.fct_order_items SET seller_id = 'missing' WHERE order_id = 'o2'"
    )
    fixture_con.execute(
        "UPDATE olist.fct_order_payments SET payment_value = -1 WHERE order_id = 'o4'"
    )
    fixture_con.execute(
        "UPDATE olist.fct_orders SET order_status = 'teleported' WHERE order_id = 'o4'"
    )
    failed = _failed(run_quality_checks(fixture_con, prefix="olist_", raise_on_error=False))
    assert {"olist_relationships", "olist_invalid_values", "olist_accepted_values"} <= failed
