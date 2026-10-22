"""SIMULATED experiment: design loading, assignment, simulator and data-quality checks."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from marketplace_analytics.config import load_settings
from marketplace_analytics.data.warehouse import connect, run_quality_checks, run_sql_layer
from marketplace_analytics.experiments.design import load_experiment
from marketplace_analytics.experiments.simulate import (
    assign_variant,
    assignment_bucket,
    simulate_experiment,
)
from marketplace_analytics.experiments.validation import observed_user_table


@pytest.fixture(scope="module")
def experiment():
    cfg = load_settings().section("experiment")
    design, population, scenarios = load_experiment(cfg)
    return design, population, {s.name: s for s in scenarios}, cfg


def test_assignment_is_deterministic_and_balanced():
    ids = [f"user-{i}" for i in range(20_000)]
    first = assign_variant(ids, "salt-a", 0.5)
    again = assign_variant(ids, "salt-a", 0.5)
    assert (first == again).all()  # stable for the same user and salt
    share = (first == "treatment").mean()
    assert abs(share - 0.5) < 4 * np.sqrt(0.25 / len(ids))  # within ~4 SE
    other = assign_variant(ids, "salt-b", 0.5)
    agreement = (first == other).mean()
    assert 0.45 < agreement < 0.55  # a new salt re-randomises
    buckets = assignment_bucket(ids, "salt-a")
    assert buckets.min() >= 0 and buckets.max() < 1


def test_assignment_respects_unequal_split():
    ids = [str(i) for i in range(20_000)]
    share = (assign_variant(ids, "s", 0.2) == "treatment").mean()
    assert abs(share - 0.2) < 4 * np.sqrt(0.16 / len(ids))


def test_simulation_is_reproducible_and_seed_dependent(experiment):
    design, population, scenarios, _ = experiment
    a = simulate_experiment(design, population, scenarios["positive"], seed=1, n_users=2000)
    b = simulate_experiment(design, population, scenarios["positive"], seed=1, n_users=2000)
    c = simulate_experiment(design, population, scenarios["positive"], seed=2, n_users=2000)
    pd.testing.assert_frame_equal(a.outcomes, b.outcomes)
    assert not a.outcomes["purchased"].equals(c.outcomes["purchased"])


def test_simulated_tables_are_internally_consistent(experiment):
    design, population, scenarios, _ = experiment
    sim = simulate_experiment(design, population, scenarios["guardrail_harm"], 3, n_users=5000)
    o = sim.outcomes
    assert o["user_id"].is_unique and sim.users["user_id"].is_unique
    assert (o["order_value"].notna() == o["purchased"]).all()
    assert (o["checkout_seconds"].notna() == o["purchased"]).all()
    assert (o["order_cancelled"].notna() == o["purchased"]).all()
    assert (o["order_value"].dropna() > 0).all()
    per_user = sim.assignment_events.groupby("user_id")["variant"].nunique()
    assert (per_user == 1).all()  # stable assignment across repeat exposures
    assert set(sim.assignment_events["user_id"]) == set(sim.users["user_id"])


def test_truth_is_kept_out_of_analysis_tables(experiment):
    design, population, scenarios, _ = experiment
    sim = simulate_experiment(design, population, scenarios["positive"], 4, n_users=1000)
    analysis_columns = set(sim.users) | set(sim.outcomes) | set(sim.assignment_events)
    assert not any(c.startswith("true_") or c == "p_conversion" for c in analysis_columns)
    assert sim.truth["true_conversion_effect_abs"] == scenarios["positive"].conversion_abs


def test_aa_scenario_ignores_any_effect_settings(experiment):
    design, population, scenarios, _ = experiment
    aa = scenarios["aa"]
    assert aa.identical_arms
    assert aa.as_record()["true_conversion_effect_abs"] == 0.0


def test_simulator_reproduces_assumed_rates(experiment):
    """Large-sample check that the generator honours its assumptions (tolerance ~5 SE)."""
    design, population, scenarios, _ = experiment
    scen = scenarios["positive"]
    sim = simulate_experiment(design, population, scen, 11, n_users=60_000)
    df = observed_user_table(sim)
    control = df[df["variant"] == "control"]["purchased"].mean()
    treat = df[df["variant"] == "treatment"]["purchased"].mean()
    expected = population.expected_baseline_conversion()
    se = np.sqrt(0.25 / 30_000)
    assert abs(control - expected) < 5 * se
    assert abs((treat - control) - scen.conversion_abs) < 5 * np.sqrt(2) * se


def test_config_rejects_non_string_scenario_names(experiment):
    *_, cfg = experiment
    bad = copy.deepcopy(cfg)
    bad["scenarios"][None] = {"description": "YAML parsed `null:` as None"}
    with pytest.raises(ValueError, match="non-empty strings"):
        load_experiment(bad)


def test_config_rejects_unknown_scenario_keys(experiment):
    *_, cfg = experiment
    bad = copy.deepcopy(cfg)
    bad["scenarios"]["typo"] = {"description": "x", "conversion_ab": 0.01}
    with pytest.raises(ValueError, match="unknown keys"):
        load_experiment(bad)


@pytest.fixture
def sim_con(experiment, tmp_path):
    design, population, scenarios, _ = experiment
    sims = [
        simulate_experiment(design, population, scenarios[n], 5 + i, n_users=3000)
        for i, n in enumerate(["aa", "positive"])
    ]
    # File name must not equal a schema name (DuckDB catalog "sim" vs schema "sim").
    con = connect(tmp_path / "experiment_test.duckdb")
    for name in ("users", "assignment_events", "outcomes"):
        df = pd.concat([getattr(s, name) for s in sims], ignore_index=True)
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE sim.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    run_sql_layer(con, "sim")
    yield con
    con.close()


def _failed(con):
    return {
        r.name for r in run_quality_checks(con, prefix="sim_", raise_on_error=False) if not r.passed
    }


def test_sim_quality_checks_pass_on_clean_data(sim_con):
    assert _failed(sim_con) == set()
    n = sim_con.execute("SELECT count(*) FROM sim.fct_experiment_users").fetchone()[0]
    assert n == 6000


def test_duplicate_and_cross_assignment_are_detected(sim_con):
    sim_con.execute(
        """INSERT INTO sim.assignment_events
           SELECT scenario, user_id,
                  CASE variant WHEN 'control' THEN 'treatment' ELSE 'control' END,
                  exposed_at + INTERVAL 1 DAY, 99
           FROM sim.assignment_events WHERE user_id = 'u0000001' AND scenario = 'aa'
           LIMIT 1"""
    )
    sim_con.execute("INSERT INTO sim.outcomes SELECT * FROM sim.outcomes LIMIT 1")
    run_sql_layer(sim_con, "sim")
    assert {"sim_single_variant", "sim_unique_grain"} <= _failed(sim_con)


def test_missing_and_invalid_outcomes_are_detected(sim_con):
    sim_con.execute("DELETE FROM sim.outcomes WHERE user_id = 'u0000002' AND scenario = 'aa'")
    sim_con.execute(
        "UPDATE sim.outcomes SET order_value = NULL WHERE purchased AND user_id IN "
        "(SELECT user_id FROM sim.outcomes WHERE purchased AND scenario = 'positive' LIMIT 1)"
    )
    run_sql_layer(sim_con, "sim")
    assert {"sim_assignment_coverage", "sim_valid_outcomes"} <= _failed(sim_con)
