"""Unit tests for outcome construction, survey-timing classification and features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from marketplace_analytics.statistics import low_review_model as lrm


def test_low_review_outcome_threshold_is_inclusive():
    out = lrm.low_review_outcome(pd.Series([1, 2, 3, 4, 5]), 2)
    assert list(out) == [1, 1, 0, 0, 0]
    assert list(lrm.low_review_outcome(pd.Series([3]), 3)) == [1]


def test_low_review_outcome_rejects_missing_scores():
    with pytest.raises(ValueError):
        lrm.low_review_outcome(pd.Series([1.0, np.nan]), 2)


def _ts(values):
    return pd.Series(pd.to_datetime(values))


def test_timing_uses_survey_sent_date_at_day_precision():
    sent = _ts(["2018-01-01", "2018-01-05", "2018-01-09"])
    delivered = _ts(["2018-01-05 10:00", "2018-01-05 23:59", "2018-01-05 08:00"])
    timing = lrm.classify_survey_timing(sent, delivered)
    # Sent date 00:00 on the delivery day is "same_day", not "pre", even though the
    # timestamp 00:00 is earlier than the delivery time.
    assert list(timing) == ["pre", "same_day", "post"]


def test_timing_by_answer_timestamp():
    sent = _ts(["2018-01-04", "2018-01-04"])
    delivered = _ts(["2018-01-05 10:00", "2018-01-05 10:00"])
    answered = _ts(["2018-01-05 09:59", "2018-01-05 10:01"])
    timing = lrm.classify_survey_timing(sent, delivered, answered, rule="answered")
    assert list(timing) == ["pre", "post"]


def test_timing_rejects_missing_dates_and_unknown_rule():
    sent = _ts(["2018-01-04"])
    with pytest.raises(ValueError):
        lrm.classify_survey_timing(sent, _ts([None]))
    with pytest.raises(ValueError):
        lrm.classify_survey_timing(_ts([None]), _ts(["2018-01-05"]))
    with pytest.raises(ValueError):
        lrm.classify_survey_timing(sent, _ts(["2018-01-05"]), rule="answered")
    with pytest.raises(ValueError):
        lrm.classify_survey_timing(sent, _ts(["2018-01-05"]), rule="bogus")


@pytest.mark.parametrize(
    ("delay", "expected"),
    [
        (-10, "on_time"),
        (0, "on_time"),
        (1, "late_1_3"),
        (3, "late_1_3"),
        (4, "late_4_7"),
        (7, "late_4_7"),
        (8, "late_8_plus"),
        (60, "late_8_plus"),
    ],
)
def test_delay_category_boundaries(delay, expected):
    assert lrm.delay_category(pd.Series([delay])).iloc[0] == expected


def test_experience_cells_merge_sparse_severe_delay_within_timing():
    delay = pd.Series(["late_8_plus"] * 2 + ["late_4_7"] * 3 + ["late_8_plus"] * 60 + ["on_time"])
    timing = pd.Series(["post"] * 5 + ["pre"] * 60 + ["post"])
    cells = lrm.experience_cells(delay, timing, min_cell=50)
    assert set(cells[:5]) == {"late_4_plus|post"}  # sparse 8+ merged in post
    assert set(cells[5:65]) == {"late_8_plus|pre"}  # enough 8+ in pre, kept
    assert cells.iloc[-1] == "on_time|post"


def test_group_categories_keeps_unknown_and_pools_tail():
    cats = pd.Series(["a"] * 5 + ["b"] * 4 + ["c"] * 2 + ["unknown"])
    out = lrm.group_categories(cats, top_n=2)
    assert out.value_counts().to_dict() == {"a": 5, "b": 4, "other": 2, "unknown": 1}


def _eligible_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3", "o4"],
            "primary_seller_id": ["s1", "s1", "s2", "s3"],
            "is_delivery_measurable": [True, True, True, False],
            "purchased_at": pd.to_datetime(["2018-01-01 10:00"] * 4),
            "purchase_date": pd.to_datetime(["2018-01-01"] * 4),
            "purchase_month": ["2018-01"] * 4,
            "delivered_to_customer_at": pd.to_datetime(
                ["2018-01-10 12:00", "2018-01-20 15:00", "2018-01-15 09:00", None]
            ),
            "estimated_delivery_date": pd.to_datetime(
                ["2018-01-15", "2018-01-15", "2018-01-15", "2018-01-15"]
            ),
            "estimated_delivery_days": [14, 14, 14, 14],
            "delivery_delay_days": [-5, 5, 0, np.nan],
            "review_score": [5, 1, 4, np.nan],
            "review_count": [1, 2, 1, 0],
            "review_survey_sent_date": pd.to_datetime(
                ["2018-01-11", "2018-01-16", "2017-12-31", None]
            ),
            "review_answered_at": pd.to_datetime(
                ["2018-01-12 08:00", "2018-01-17 08:00", "2018-01-16 08:00", None]
            ),
            "items_value": [100.0, 50.0, 80.0, 10.0],
            "freight_value": [25.0, 50.0, 20.0, 5.0],
            "order_gross_value": [125.0, 100.0, 100.0, 15.0],
            "item_count": [1, 3, 2, 1],
            "distinct_sellers": [1, 2, 1, 1],
            "primary_category": ["bed_bath_table", "toys", "unknown", "toys"],
            "customer_region": ["Southeast", "North", "South", "South"],
        }
    )


def test_population_funnel_counts_each_exclusion():
    eligible, funnel = lrm.build_population(_eligible_rows())
    assert list(funnel["remaining"]) == [4, 3, 3, 2]
    assert list(funnel["removed"]) == [0, 1, 0, 1]  # o4 not measurable; o3 survey < purchase
    assert list(eligible["order_id"]) == ["o1", "o2"]


def test_prepare_model_frame_features():
    rows = _eligible_rows().iloc[:3]
    frame, refs = lrm.prepare_model_frame(rows, low_review_max_score=2, top_categories=5)
    f = frame.set_index("order_id")
    assert list(f["low_review"]) == [0, 1, 0]
    assert list(f["late"]) == [0, 1, 0]
    # o3 delivered ON the promised day: not late by date, late by timestamp.
    assert f.loc["o3", "late"] == 0 and f.loc["o3", "late_ts"] == 1
    assert list(f["timing"]) == ["post", "pre", "pre"]  # o2: sent 16th, delivered 20th
    assert list(f["basket"]) == ["single_item", "multi_seller", "multi_item_one_seller"]
    assert f.loc["o1", "freight_share_10pp"] == pytest.approx(2.0)  # 25 / 125 * 10
    assert f.loc["o1", "promised_weeks"] == pytest.approx(2.0)
    assert f.loc["o1", "log_items_value"] == pytest.approx(np.log(100))
    assert f.loc["o3", "category"] == "unknown"
    assert f.loc["o3", "unexplained_early_survey"] == 1  # sent before delivery AND promise
    assert f.loc["o2", "single_review"] == 0
    assert refs.region == "Southeast" and refs.timing == "post"
    assert refs.category in {"bed_bath_table", "toys"}


def test_specs_are_consistent():
    refs = lrm.References(category="bed_bath_table", month="2018-01")
    specs = lrm.build_specs(refs)
    names = [s.name for s in specs]
    assert len(names) == len(set(names))
    for spec in specs:
        assert spec.late_term in spec.formula
        assert "review_has_comment" not in spec.formula  # no post-review leakage
