"""Generate a SIMULATED user-level checkout experiment.

Output tables (all synthetic):

* ``users``             one row per eligible user: pre-treatment attributes.
* ``assignment_events`` one row per checkout visit (exposure) with the assigned variant.
* ``outcomes``          one row per user: observed outcomes during the attribution window.

The true parameters are returned separately (``SimulatedExperiment.truth``) and are
never part of the analysis tables.

Data-generating assumptions (documented in docs/experiment_plan.md):
* Assignment: deterministic hash of (salt, user_id) -> stable, reproducible, 50/50.
* Purchase: Bernoulli(baseline[device, customer_type] + effect).
* Checkout error: Bernoulli(baseline_error[device] + effect), independent of purchase.
* Order value (purchasers): log-normal; treatment can scale it.
* Cancellation (purchasers): Bernoulli(baseline + effect).
* Checkout time (purchasers): log-normal by device; treatment can scale it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from marketplace_analytics.experiments.design import (
    ExperimentDesign,
    Population,
    Scenario,
)


def assignment_bucket(user_ids: pd.Series | list[str], salt: str) -> np.ndarray:
    """Uniform [0, 1) bucket from SHA-256 of 'salt:user_id' (stable across runs/machines)."""
    out = np.empty(len(user_ids))
    for i, uid in enumerate(user_ids):
        digest = hashlib.sha256(f"{salt}:{uid}".encode()).digest()
        out[i] = int.from_bytes(digest[:8], "big") / 2**64
    return out


def assign_variant(
    user_ids: pd.Series | list[str], salt: str, treatment_share: float
) -> np.ndarray:
    """Deterministic user-level assignment: same user + salt -> same variant, always."""
    return np.where(assignment_bucket(user_ids, salt) < treatment_share, "treatment", "control")


@dataclass
class SimulatedExperiment:
    scenario: str
    users: pd.DataFrame
    assignment_events: pd.DataFrame
    outcomes: pd.DataFrame
    truth: dict  # true parameters: for simulator validation only


def _clip01(p: np.ndarray) -> np.ndarray:
    if (p < 0).any() or (p > 1).any():
        raise ValueError("Scenario effect pushes a probability outside [0, 1]")
    return p


def simulate_experiment(
    design: ExperimentDesign,
    population: Population,
    scenario: Scenario,
    seed: int,
    n_users: int | None = None,
    user_prefix: str = "u",
    salt_suffix: str = "",
) -> SimulatedExperiment:
    rng = np.random.default_rng(seed)
    n = n_users or design.planned_users

    # Pre-treatment population
    user_id = np.array([f"{user_prefix}{i:07d}" for i in range(n)])
    devices = list(population.device_shares)
    device = rng.choice(devices, size=n, p=list(population.device_shares.values()))
    customer_type = np.where(rng.random(n) < population.new_customer_share, "new", "returning")
    day = rng.integers(0, design.duration_days, size=n)
    start = pd.Timestamp(design.start_date)
    first_exposure = (
        start
        + pd.to_timedelta(day, unit="D")
        + pd.to_timedelta(rng.integers(0, 86_400, size=n), unit="s")
    )

    # The salt includes the scenario, so each simulated experiment is randomised independently.
    salt = f"{design.salt}:{scenario.name}{salt_suffix}"
    variant = assign_variant(user_id, salt, design.treatment_share)
    treated = (variant == "treatment") & (not scenario.identical_arms)

    # Outcomes
    base_conv = np.array(
        [population.baseline_conversion[d][c] for d, c in zip(device, customer_type, strict=True)]
    )
    p_conv = _clip01(base_conv + treated * scenario.conversion_abs)
    purchased = rng.random(n) < p_conv

    base_err = np.array([population.baseline_error_rate[d] for d in device])
    had_error = rng.random(n) < _clip01(base_err + treated * scenario.error_rate_abs)

    value = np.exp(
        np.log(population.order_value_median) + population.order_value_sigma * rng.normal(size=n)
    )
    value *= np.where(treated, scenario.order_value_multiplier, 1.0)
    p_cancel = _clip01(
        np.full(n, population.baseline_cancellation_rate) + treated * scenario.cancellation_abs
    )
    cancelled = purchased & (rng.random(n) < p_cancel)
    seconds_median = np.array([population.checkout_seconds_median[d] for d in device])
    seconds = np.exp(
        np.log(seconds_median) + population.checkout_seconds_sigma * rng.normal(size=n)
    )
    seconds *= np.where(treated, scenario.checkout_seconds_multiplier, 1.0)

    users = pd.DataFrame(
        {
            "scenario": scenario.name,
            "user_id": user_id,
            "device": device,
            "customer_type": customer_type,
        }
    )
    outcomes = pd.DataFrame(
        {
            "scenario": scenario.name,
            "user_id": user_id,
            "purchased": purchased,
            "order_value": np.where(purchased, np.round(value, 2), np.nan),
            "order_cancelled": np.where(purchased, cancelled, pd.NA),
            "checkout_error": had_error,
            "checkout_seconds": np.where(purchased, np.round(seconds, 1), np.nan),
        }
    )
    outcomes["order_cancelled"] = outcomes["order_cancelled"].astype("boolean")

    # Exposure log: 1-3 checkout visits per user, all with the same variant.
    visits = rng.choice(
        list(population.exposures_per_user),
        size=n,
        p=list(population.exposures_per_user.values()),
    )
    idx = np.repeat(np.arange(n), visits)
    extra_offset = np.where(
        np.concatenate([[False], idx[1:] == idx[:-1]]),
        rng.integers(60, 6 * 86_400, size=len(idx)),
        0,
    )
    events = pd.DataFrame(
        {
            "scenario": scenario.name,
            "user_id": user_id[idx],
            "variant": variant[idx],
            "exposed_at": first_exposure[idx] + pd.to_timedelta(extra_offset, unit="s"),
        }
    )
    events = events.sort_values(["user_id", "exposed_at"], ignore_index=True)
    events["exposure_number"] = events.groupby("user_id").cumcount() + 1

    truth = scenario.as_record() | {
        "seed": seed,
        "n_users": n,
        "true_control_conversion": population.expected_baseline_conversion(),
    }
    return SimulatedExperiment(scenario.name, users, events, outcomes, truth)
