"""End-to-end SIMULATED experiment pipeline on a small configuration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from marketplace_analytics.config import load_settings
from marketplace_analytics.data.warehouse import connect
from marketplace_analytics.experiments.power import guardrail_sensitivity, noninferiority_n_per_arm
from marketplace_analytics.reporting.experiment import run_experiment


def test_noninferiority_sample_size_formula():
    # Proportion with p = 0.05, margin 0.5 pp: n = 2 (z.975 + z.8)^2 p(1-p) / m^2
    sd = np.sqrt(0.05 * 0.95)
    assert noninferiority_n_per_arm(sd, 0.005) == pytest.approx(
        2 * (1.959964 + 0.841621) ** 2 * 0.0475 / 0.005**2, rel=1e-3
    )


def test_guardrail_sensitivity_flags_unattainable_margins():
    control = pd.DataFrame(
        {
            "net_order_value": np.r_[np.full(500, 0.0), np.full(500, 200.0)],
            "checkout_error": np.r_[np.ones(50), np.zeros(950)].astype(bool),
            "cancelled_order": np.r_[np.ones(10), np.zeros(990)].astype(bool),
        }
    )
    margins = {
        "revenue_per_user_rel": 0.02,
        "checkout_error_rate_abs": 0.005,
        "cancellation_rate_abs": 0.005,
    }
    small = guardrail_sensitivity(control, margins, n_per_arm=1_000).set_index("metric")
    huge = guardrail_sensitivity(control, margins, n_per_arm=10_000_000).set_index("metric")
    assert not small["can_show_noninferiority_at_zero_effect"].any()
    assert huge["can_show_noninferiority_at_zero_effect"].all()
    assert small.loc["net_order_value_per_user", "margin_abs"] == pytest.approx(2.0)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    settings = load_settings(root=tmp_path_factory.mktemp("repo"))
    settings.raw["experiment"]["validation"]["srm_logging_losses"] = [0.10]
    result = run_experiment(settings, replications=20, n_users=4000)
    return settings, result


def test_pipeline_writes_sim_tables_for_downstream_use(run):
    settings, result = run
    con = connect(settings.paths.warehouse)
    try:
        tables = set(
            con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'sim'"
            ).df()["table_name"]
        )
        for name in (
            "fct_experiment_users",
            "agg_variant_metrics",
            "daily_assignments",
            "metric_results",
            "decisions",
            "segment_results",
            "srm_checks",
            "power_curve",
            "guardrail_sensitivity",
            "validation_summary",
            "simulation_truth_validation_only",
        ):
            assert name in tables, name
        users = con.execute("SELECT count(*) FROM sim.fct_experiment_users").fetchone()[0]
        olist = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'olist'"
        ).fetchone()[0]
    finally:
        con.close()
    n_scenarios = len(result.tables["decisions"])
    assert users == 4000 * n_scenarios
    assert olist == 0  # the experiment never creates or reads historical tables


def test_pipeline_outputs_are_consistent(run):
    _, result = run
    t = result.tables
    assert (t["quality_checks"]["failing_rows"] == 0).all()
    decisions = t["decisions"].set_index("scenario")["decision"]
    assert decisions["aa"] in {"A/A PASS", "A/A FAIL"}
    allowed = {"LAUNCH", "REJECT", "CONTINUE TESTING", "INVALID"}
    assert set(decisions.drop("aa")) <= allowed
    primary = t["metric_results"].query("metric == 'purchase_completion'")
    agg = t["variant_metrics"]
    assert primary["n_treatment"].sum() + primary["n_control"].sum() == agg["assigned_users"].sum()
    assert len(result.figures) == 6 and all(p.exists() for p in result.figures)
    assert "simulation_truth_validation_only.csv" not in {p.name for p in result.figures}
