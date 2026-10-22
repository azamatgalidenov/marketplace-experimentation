"""SIMULATED checkout experiment: design parameters and scenario definitions.

``ExperimentDesign`` holds what an analyst would fix before seeing outcomes (metrics,
alpha, MDE, margins, segments). ``Scenario`` holds the true data-generating effects,
which only the simulator and the validation code may read; the analysis never does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PRIMARY_METRIC = "purchase_completion"
VARIANTS = ("control", "treatment")
SEGMENTS = ("device", "customer_type")


@dataclass(frozen=True)
class ExperimentDesign:
    """Pre-registered analysis plan."""

    name: str
    salt: str
    alpha: float
    power: float
    mde_abs: float
    planning_baseline_conversion: float
    practical_threshold_abs: float
    srm_alpha: float
    treatment_share: float
    segment_min_users_per_arm: int
    guardrail_margins: dict[str, float]
    duration_days: int
    daily_eligible_users: int
    start_date: str

    @property
    def planned_users(self) -> int:
        return self.duration_days * self.daily_eligible_users


@dataclass(frozen=True)
class Population:
    """Assumed (synthetic) user population and control-arm behaviour."""

    device_shares: dict[str, float]
    new_customer_share: float
    exposures_per_user: dict[int, float]
    baseline_conversion: dict[str, dict[str, float]]
    baseline_error_rate: dict[str, float]
    baseline_cancellation_rate: float
    order_value_median: float
    order_value_sigma: float
    checkout_seconds_median: dict[str, float]
    checkout_seconds_sigma: float

    def expected_baseline_conversion(self) -> float:
        """Population-weighted control conversion implied by the assumptions."""
        total = 0.0
        for device, share in self.device_shares.items():
            rates = self.baseline_conversion[device]
            total += share * (
                (1 - self.new_customer_share) * rates["returning"]
                + self.new_customer_share * rates["new"]
            )
        return total


@dataclass(frozen=True)
class Scenario:
    """True treatment effects for one simulated world (never visible to the analysis)."""

    name: str
    description: str
    identical_arms: bool = False
    conversion_abs: float = 0.0
    error_rate_abs: float = 0.0
    cancellation_abs: float = 0.0
    order_value_multiplier: float = 1.0
    checkout_seconds_multiplier: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_record(self) -> dict[str, Any]:
        return {
            "scenario": self.name,
            "description": self.description,
            "identical_arms": self.identical_arms,
            "true_conversion_effect_abs": 0.0 if self.identical_arms else self.conversion_abs,
            "true_error_rate_effect_abs": 0.0 if self.identical_arms else self.error_rate_abs,
            "true_cancellation_effect_abs": 0.0 if self.identical_arms else self.cancellation_abs,
            "true_order_value_multiplier": 1.0
            if self.identical_arms
            else self.order_value_multiplier,
            "true_checkout_seconds_multiplier": 1.0
            if self.identical_arms
            else self.checkout_seconds_multiplier,
        }


def load_experiment(cfg: dict[str, Any]) -> tuple[ExperimentDesign, Population, list[Scenario]]:
    design = ExperimentDesign(
        name=cfg["name"],
        salt=cfg["salt"],
        alpha=float(cfg["alpha"]),
        power=float(cfg["power"]),
        mde_abs=float(cfg["mde_abs"]),
        planning_baseline_conversion=float(cfg["planning_baseline_conversion"]),
        practical_threshold_abs=float(cfg["practical_threshold_abs"]),
        srm_alpha=float(cfg["srm_alpha"]),
        treatment_share=float(cfg["treatment_share"]),
        segment_min_users_per_arm=int(cfg["segment_min_users_per_arm"]),
        guardrail_margins={k: float(v) for k, v in cfg["guardrail_margins"].items()},
        duration_days=int(cfg["duration_days"]),
        daily_eligible_users=int(cfg["daily_eligible_users"]),
        start_date=str(cfg["start_date"]),
    )
    population = Population(
        device_shares={k: float(v) for k, v in cfg["device_shares"].items()},
        new_customer_share=float(cfg["new_customer_share"]),
        exposures_per_user={int(k): float(v) for k, v in cfg["exposures_per_user"].items()},
        baseline_conversion=cfg["baseline_conversion"],
        baseline_error_rate={k: float(v) for k, v in cfg["baseline_error_rate"].items()},
        baseline_cancellation_rate=float(cfg["baseline_cancellation_rate"]),
        order_value_median=float(cfg["order_value_median"]),
        order_value_sigma=float(cfg["order_value_sigma"]),
        checkout_seconds_median={k: float(v) for k, v in cfg["checkout_seconds_median"].items()},
        checkout_seconds_sigma=float(cfg["checkout_seconds_sigma"]),
    )
    known = {f for f in Scenario.__dataclass_fields__ if f not in ("name", "extra")}
    scenarios = []
    for name, spec in cfg["scenarios"].items():
        if not isinstance(name, str) or not name:
            # YAML turns keys such as `null`, `yes` or `no` into non-strings.
            raise ValueError(f"Scenario names must be non-empty strings, got {name!r}")
        unknown = set(spec) - known
        if unknown:
            raise ValueError(f"Scenario '{name}' has unknown keys: {sorted(unknown)}")
        scenarios.append(Scenario(name=name, **spec))
    _validate(design, population)
    return design, population, scenarios


def _validate(design: ExperimentDesign, population: Population) -> None:
    if abs(sum(population.device_shares.values()) - 1) > 1e-9:
        raise ValueError("device_shares must sum to 1")
    if abs(sum(population.exposures_per_user.values()) - 1) > 1e-9:
        raise ValueError("exposures_per_user probabilities must sum to 1")
    if not 0 < design.treatment_share < 1:
        raise ValueError("treatment_share must be in (0, 1)")
    if set(population.baseline_conversion) != set(population.device_shares):
        raise ValueError("baseline_conversion must define every device")
