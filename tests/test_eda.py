"""End-to-end EDA on the fixture: queries, reconciliation, tables, charts."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from marketplace_analytics.reporting.eda import add_wilson, late_vs_on_time_review, run_eda


@pytest.fixture(scope="module")
def eda_result(built_fixture_warehouse):
    return run_eda(built_fixture_warehouse)


def test_eda_writes_all_outputs(eda_result, built_fixture_warehouse):
    paths = built_fixture_warehouse.paths
    assert eda_result.reconciliation["match"].all()
    assert len(eda_result.figures) == 11
    assert all(p.exists() and p.stat().st_size > 0 for p in eda_result.figures)
    results = paths.results_dir / "eda"
    assert (results / "reconciliation_python_vs_sql.csv").exists()
    numbers = json.loads((results / "key_numbers.json").read_text())
    assert numbers["orders_in_window"] == 3
    assert numbers["aov_gross_delivered"] == pytest.approx(192.5)


def test_eda_tables_use_correct_populations(eda_result):
    t = eda_result.tables
    status = t["eda_order_status"].set_index("order_status")
    assert status["orders"].sum() == 3  # canceled o3 is outside the window
    assert status["share"].sum() == pytest.approx(1.0)
    monthly = t["eda_monthly_orders"]
    assert monthly["orders"].sum() == 3
    assert monthly["delivered_orders"].sum() == 2
    # Category value is item level: o1's two lines go to two categories, once each.
    cats = t["eda_categories"].set_index("category_name")
    assert float(cats.loc["bed_bath_table", "gmv"]) == pytest.approx(300.0)  # 100 + 200
    assert float(cats.loc["pc_gamer", "gmv"]) == pytest.approx(50.0)
    assert float(cats["gmv"].sum()) == pytest.approx(350.0)  # delivered items only


def test_add_wilson_appends_rate_and_interval():
    df = pd.DataFrame({"x": [5, 0], "n": [10, 4]})
    out = add_wilson(df, "x", "n", "low")
    assert list(out["low_rate"]) == [0.5, 0.0]
    assert (out["low_ci_low"] <= out["low_rate"]).all()
    assert (out["low_ci_high"] >= out["low_rate"]).all()


def test_late_vs_on_time_review_excludes_pre_delivery_surveys():
    table = pd.DataFrame(
        {
            "is_late": [False, True, True],
            "survey_sent_before_delivery": [False, False, True],
            "reviewed_orders": [100, 20, 30],
            "low_reviews": [10, 6, 24],
        }
    )
    out = late_vs_on_time_review(table).set_index("population")
    overall = out.loc["All measurable reviewed deliveries"]
    assert overall["late_low_rate"] == pytest.approx(30 / 50)
    restricted = out.loc["Survey sent on/after delivery date"]
    assert restricted["late_low_rate"] == pytest.approx(6 / 20)
    assert restricted["on_time_low_rate"] == pytest.approx(0.1)
