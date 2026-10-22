"""Sample size, power and minimum detectable effect for a two-proportion test."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import optimize, stats
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize


def required_n_per_arm(
    baseline: float, mde_abs: float, alpha: float = 0.05, power: float = 0.8, ratio: float = 1.0
) -> int:
    """Users per arm (control arm; treatment = ratio x control) to detect ``mde_abs``.

    Uses statsmodels' normal power analysis on Cohen's h (arcsine-transformed difference).
    """
    h = proportion_effectsize(baseline + mde_abs, baseline)
    n = NormalIndPower().solve_power(
        effect_size=h, alpha=alpha, power=power, ratio=ratio, alternative="two-sided"
    )
    return math.ceil(n)


def required_n_closed_form(
    baseline: float, mde_abs: float, alpha: float = 0.05, power: float = 0.8
) -> int:
    """Textbook formula (equal arms): pooled variance under H0, unpooled under H1."""
    p1, p2 = baseline, baseline + mde_abs
    pbar = (p1 + p2) / 2
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    num = za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return math.ceil(num**2 / mde_abs**2)


def power_for_effect(
    baseline: float, effect_abs: float, n_per_arm: float, alpha: float = 0.05, ratio: float = 1.0
) -> float:
    if effect_abs == 0:
        return alpha
    h = proportion_effectsize(baseline + effect_abs, baseline)
    return float(
        NormalIndPower().power(
            effect_size=h, nobs1=n_per_arm, alpha=alpha, ratio=ratio, alternative="two-sided"
        )
    )


def mde_for_n(
    baseline: float, n_per_arm: float, alpha: float = 0.05, power: float = 0.8, ratio: float = 1.0
) -> float:
    """Smallest absolute lift detectable with the given power (positive direction)."""
    upper = 1 - baseline - 1e-9
    return float(
        optimize.brentq(
            lambda d: power_for_effect(baseline, d, n_per_arm, alpha, ratio) - power, 1e-6, upper
        )
    )


def power_curve(
    baseline: float, n_per_arm: float, effects: np.ndarray, alpha: float = 0.05
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "true_effect_abs": effects,
            "power": [power_for_effect(baseline, e, n_per_arm, alpha) for e in effects],
        }
    )


def noninferiority_n_per_arm(
    sd: float, margin_abs: float, alpha: float = 0.05, power: float = 0.8
) -> int:
    """Users per arm so that, if the true difference is 0, the two-sided (1 - alpha) CI
    excludes a deterioration of ``margin_abs`` with probability ``power``."""
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    return math.ceil(2 * (za + zb) ** 2 * sd**2 / margin_abs**2)


def guardrail_sensitivity(
    control: pd.DataFrame,
    margins: dict[str, float],
    n_per_arm: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> pd.DataFrame:
    """Can the planned sample demonstrate each guardrail's non-inferiority margin?

    ``control`` is a control-arm sample used as a stand-in for pre-period data (its mean
    and variance; no treatment information).
    """
    spec = [
        ("net_order_value_per_user", "net_order_value", "revenue_per_user_rel", True),
        ("checkout_error_rate", "checkout_error", "checkout_error_rate_abs", False),
        ("cancellation_rate", "cancelled_order", "cancellation_rate_abs", False),
    ]
    za = stats.norm.ppf(1 - alpha / 2)
    rows = []
    for metric, column, key, relative in spec:
        x = control[column].astype(float)
        mean, sd = float(x.mean()), float(x.std(ddof=1))
        margin_abs = margins[key] * mean if relative else margins[key]
        half_width = za * sd * math.sqrt(2 / n_per_arm)
        rows.append(
            {
                "metric": metric,
                "control_mean": mean,
                "control_sd": sd,
                "margin": margins[key],
                "margin_scale": "relative" if relative else "absolute",
                "margin_abs": margin_abs,
                "planned_n_per_arm": n_per_arm,
                "expected_ci_half_width_abs": half_width,
                "can_show_noninferiority_at_zero_effect": half_width < margin_abs,
                "n_per_arm_for_80pct_noninferiority": noninferiority_n_per_arm(
                    sd, margin_abs, alpha, power
                ),
            }
        )
    return pd.DataFrame(rows)
