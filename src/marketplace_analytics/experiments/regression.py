"""Logistic regression for the SIMULATED checkout experiment (secondary analysis).

The pre-registered primary decision uses the unadjusted two-proportion test
(``analysis.py``). This module adds a secondary robustness and precision analysis
(specified after the primary results; it never changes a decision):

* unadjusted logit   purchased ~ treatment                 (reproduces the raw difference)
* adjusted logit     + device + customer_type               (pre-treatment covariates only)
* interaction logit  treatment x device + customer_type     (heterogeneity test)

Only observed data are used. Covariates are fixed before assignment, so adjusting for
them cannot bias the randomised comparison; it can only sharpen it. Post-treatment
variables (checkout errors, checkout time, order value) are excluded; see
``mediator_bias_demo`` for why.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from marketplace_analytics.statistics.regression import (
    LogitFit,
    average_marginal_effect,
    average_predictions,
    fit_logit,
    performance,
    tidy,
)

DEVICE_REF = "mobile_app"
CUSTOMER_REF = "returning"
DEVICE = f"C(device, Treatment('{DEVICE_REF}'))"
CUSTOMER = f"C(customer_type, Treatment('{CUSTOMER_REF}'))"

FORMULAS = {
    "unadjusted": "purchased ~ treatment",
    "adjusted": f"purchased ~ treatment + {DEVICE} + {CUSTOMER}",
    "interaction": f"purchased ~ treatment * {DEVICE} + {CUSTOMER}",
}


def model_frame(users: pd.DataFrame) -> pd.DataFrame:
    """One row per assigned user with a 0/1 treatment flag and 0/1 outcome."""
    cols = ["user_id", "variant", "device", "customer_type", "purchased"]
    frame = users[cols].copy()
    if frame.isna().any().any():
        raise ValueError("Experiment model frame has missing values")
    frame["treatment"] = (frame["variant"] == "treatment").astype(int)
    frame["purchased"] = frame["purchased"].astype(int)
    return frame.reset_index(drop=True)


def fit_models(frame: pd.DataFrame) -> dict[str, LogitFit]:
    """Fit all three models with HC1 robust standard errors.

    The true data-generating process is additive on the probability scale, so the logit
    form is (mildly) misspecified; robust SEs keep inference valid regardless.
    """
    return {name: fit_logit(f, frame, robust=True) for name, f in FORMULAS.items()}


def treatment_effects(
    fits: dict[str, LogitFit], n_draws: int = 1000, seed: int = 0
) -> pd.DataFrame:
    """Treatment odds ratio (conditional) and average marginal effect (pp) per model."""
    rows = []
    for name, fit in fits.items():
        t = tidy(fit).set_index("term").loc["treatment"]
        ame = average_marginal_effect(fit, "treatment", 1, 0, n_draws=n_draws, seed=seed)
        rows.append(
            {
                "model": name,
                "n": fit.nobs,
                "odds_ratio": t["odds_ratio"],
                "or_ci_low": t["or_ci_low"],
                "or_ci_high": t["or_ci_high"],
                "or_p_value": t["p_value"],
                "or_note": "odds ratio in the reference device (mobile_app)"
                if name == "interaction"
                else "conditional odds ratio",
                "ame_abs": ame["ame"],
                "ame_ci_low": ame["ame_ci_low"],
                "ame_ci_high": ame["ame_ci_high"],
                "ame_ci_width": ame["ame_ci_high"] - ame["ame_ci_low"],
                "ame_se_delta": ame["ame_se_delta"],
                "ame_delta_ci_width": ame["ame_delta_ci_high"] - ame["ame_delta_ci_low"],
                **{k: v for k, v in performance(fit).items() if k in ("auc", "aic")},
            }
        )
    return pd.DataFrame(rows)


def interaction_test(fits: dict[str, LogitFit]) -> dict:
    """Likelihood-ratio test: does the treatment effect (log-odds) differ by device?"""
    full, reduced = fits["interaction"].result, fits["adjusted"].result
    lr = 2 * (full.llf - reduced.llf)
    df = int(full.df_model - reduced.df_model)
    return {"lr_statistic": float(lr), "df": df, "p_value": float(stats.chi2.sf(lr, df))}


def device_effects(fit: LogitFit, n_draws: int = 1000, seed: int = 0) -> pd.DataFrame:
    """Per-device predicted completion in each arm and the device-specific AME (pp).

    Estimated from the interaction model, averaging over the device's own users.
    """
    rows = []
    for device in sorted(fit.data["device"].unique()):
        subset = fit.data["device"] == device
        pred = average_predictions(
            fit, "treatment", [0, 1], subset=subset, n_draws=n_draws, seed=seed
        ).set_index("level")
        ame = average_marginal_effect(
            fit, "treatment", 1, 0, subset=subset, n_draws=n_draws, seed=seed
        )
        p0, p1 = pred.loc[0, "probability"], pred.loc[1, "probability"]
        rows.append(
            {
                "device": device,
                "users": int(subset.sum()),
                "pred_control": p0,
                "pred_treatment": p1,
                "ame_abs": ame["ame"],
                "ame_ci_low": ame["ame_ci_low"],
                "ame_ci_high": ame["ame_ci_high"],
                # Implied odds ratio within the device, to contrast with the pp effect.
                "implied_odds_ratio": (p1 / (1 - p1)) / (p0 / (1 - p0)),
            }
        )
    return pd.DataFrame(rows)


MEDIATOR_TRUE_TOTAL = 0.035
MEDIATOR_TRUE_DIRECT = 0.010


def _point_ame(fit: LogitFit) -> float:
    """Average marginal effect of ``treatment`` (point estimate only)."""
    df = fit.data
    return float(
        fit.result.predict(df.assign(treatment=1)).mean()
        - fit.result.predict(df.assign(treatment=0)).mean()
    )


def mediator_bias_demo(n: int = 40_000, replications: int = 200, seed: int = 0) -> pd.DataFrame:
    """SIMULATED illustration of why post-treatment variables must not be adjusted for.

    A separate toy world where the simplified checkout works partly through fewer errors:
        error    ~ Bernoulli(0.15 - 0.10 * T)
        purchase ~ Bernoulli(0.55 + 0.01 * T - 0.25 * error)
    True total effect = 0.01 + 0.10 * 0.25 = +3.5 pp; direct (not via errors) = +1.0 pp.
    "Controlling" for errors recovers only the direct part and understates the total
    effect the business actually gets.

    Repeated over ``replications`` independent toy experiments so the comparison does
    not rest on one random draw; the interval is the 2.5-97.5% range of the estimates.
    """
    rng = np.random.default_rng(seed)
    estimates: dict[str, list[float]] = {"unadjusted": [], "adjusted": []}
    for _ in range(replications):
        t = rng.integers(0, 2, n)
        error = (rng.random(n) < 0.15 - 0.10 * t).astype(int)
        purchased = (rng.random(n) < 0.55 + 0.01 * t - 0.25 * error).astype(int)
        df = pd.DataFrame({"treatment": t, "error": error, "purchased": purchased})
        estimates["unadjusted"].append(_point_ame(fit_logit("purchased ~ treatment", df)))
        estimates["adjusted"].append(_point_ame(fit_logit("purchased ~ treatment + error", df)))
    rows = [
        {
            "quantity": "True total effect",
            "estimate": MEDIATOR_TRUE_TOTAL,
            "ci_low": np.nan,
            "ci_high": np.nan,
            "replications": replications,
        },
        {
            "quantity": "True direct effect",
            "estimate": MEDIATOR_TRUE_DIRECT,
            "ci_low": np.nan,
            "ci_high": np.nan,
            "replications": replications,
        },
    ]
    for label, key in [
        ("Estimate without mediator (correct)", "unadjusted"),
        ("Estimate adjusting for errors (biased)", "adjusted"),
    ]:
        values = np.array(estimates[key])
        rows.append(
            {
                "quantity": label,
                "estimate": float(values.mean()),
                "ci_low": float(np.quantile(values, 0.025)),
                "ci_high": float(np.quantile(values, 0.975)),
                "replications": replications,
            }
        )
    return pd.DataFrame(rows)
