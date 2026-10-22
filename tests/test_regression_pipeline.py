"""End-to-end regression run on a synthetic model frame.

The frame below is generated test data with the same columns as the real model frame;
it exists only to exercise the pipeline and check that counts reconcile.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from marketplace_analytics.config import load_settings
from marketplace_analytics.reporting.regression import run_regression
from marketplace_analytics.statistics import low_review_model as lrm


def synthetic_model_frame(n: int = 6000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    late = rng.binomial(1, 0.15, n)
    # Late orders mostly get pre-delivery surveys, as in the real data.
    timing = np.where(
        late == 1,
        rng.choice(["pre", "same_day", "post"], n, p=[0.6, 0.15, 0.25]),
        rng.choice(["pre", "same_day", "post"], n, p=[0.02, 0.05, 0.93]),
    )
    delay = np.where(late == 1, rng.choice([2, 5, 10], n), rng.integers(-20, 1, n))
    df = pd.DataFrame(
        {
            "order_id": [f"o{i}" for i in range(n)],
            "seller": rng.integers(0, 150, n).astype(str),
            "late": late,
            "late_ts": np.maximum(late, rng.binomial(1, 0.02, n)),
            "delay_cat": lrm.delay_category(pd.Series(delay)),
            "timing": timing,
            "timing_answer": np.where(timing == "pre", "pre", "post"),
            "promised_weeks": rng.uniform(1, 6, n),
            "log_items_value": np.log(rng.uniform(10, 500, n)),
            "freight_share_10pp": rng.uniform(0.2, 5, n),
            "basket": rng.choice(
                ["single_item", "multi_item_one_seller", "multi_seller"], n, p=[0.85, 0.12, 0.03]
            ),
            "category": rng.choice(["bed_bath_table", "health_beauty", "other", "unknown"], n),
            "region": rng.choice(["Southeast", "South", "Northeast", "North", "Center-West"], n),
            "month": rng.choice(["2018-01", "2018-02", "2018-03"], n),
            "single_review": rng.binomial(1, 0.98, n),
        }
    )
    df["same_day"] = (df["timing"] == "same_day").astype(int)
    df["cell"] = lrm.experience_cells(df["delay_cat"], df["timing"], min_cell=50)
    df["unexplained_early_survey"] = ((df["timing"] == "pre") & (df["late"] == 0)).astype(int)
    eta = -2.3 + 0.9 * late + 1.5 * late * (timing == "pre") + 0.8 * (df["basket"] != "single_item")
    df["low_review"] = rng.binomial(1, 1 / (1 + np.exp(-eta)))
    df["low_review_le3"] = np.maximum(df["low_review"], rng.binomial(1, 0.08, n))
    return df


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    settings = load_settings(root=tmp_path_factory.mktemp("repo"))
    settings.raw["regression"]["simulation_draws"] = 200
    return run_regression(settings, frame=synthetic_model_frame()), settings


def test_observation_counts_reconcile_across_specs(result):
    res, _ = result
    frame = res.frame
    comp = res.tables["specification_comparison"].set_index("spec")
    assert comp.loc["M1", "n"] == len(frame)
    assert comp.loc["M3", "n"] == len(frame)
    assert comp.loc["M4", "n"] == (frame["timing"] == "post").sum()
    assert comp.loc["M5", "n"] == comp.loc["M4", "n"]
    assert comp.loc["T1", "n"] == frame["timing"].isin(["post", "same_day"]).sum()
    assert comp.loc["T2", "n"] == (frame["timing_answer"] == "post").sum()
    assert comp.loc["T4", "n"] == (frame["unexplained_early_survey"] == 0).sum()
    assert comp.loc["A3", "n"] == frame["single_review"].sum()
    assert comp.loc["A4", "n"] + comp.loc["A4", "excluded_rows"] == len(frame)
    assert comp.loc["M3", "ame_population_n"] == (frame["timing"] == "post").sum()


def test_simple_restricted_model_reproduces_raw_rates(result):
    """M4 is saturated: its AME must equal the raw late vs on-time difference."""
    res, _ = result
    post = res.frame[res.frame["timing"] == "post"]
    raw = (
        post.loc[post.late == 1, "low_review"].mean()
        - post.loc[post.late == 0, "low_review"].mean()
    )
    comp = res.tables["specification_comparison"].set_index("spec")
    assert comp.loc["M4", "late_ame_pp"] == pytest.approx(raw * 100, abs=1e-6)


def test_outputs_written(result):
    res, settings = result
    out = settings.paths.results_dir / "regression"
    for name in ("specification_comparison", "coefficients_all_specs", "vif_M3", "cmh_tests"):
        assert (out / f"{name}.csv").exists()
    assert (out / "key_numbers.json").exists()
    assert len(res.figures) == 5 and all(p.exists() for p in res.figures)
    coefs = res.tables["coefficients_all_specs"]
    assert np.isfinite(coefs["coef"]).all()
    assert (coefs["coef"].abs() < 20).all(), "a coefficient diverged (separation)"
