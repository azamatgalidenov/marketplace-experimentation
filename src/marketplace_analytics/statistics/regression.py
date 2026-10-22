"""Logistic-regression helpers: fitting, tidy output, diagnostics, marginal effects.

Generic: nothing here knows about Olist. The domain model lives in ``low_review_model``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import patsy
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.outliers_influence import variance_inflation_factor


@dataclass
class LogitFit:
    """A fitted binomial GLM plus the exact data it was fitted on."""

    result: object  # statsmodels GLMResultsWrapper
    data: pd.DataFrame
    formula: str
    cluster: str | None

    @property
    def nobs(self) -> int:
        return int(self.result.nobs)


def fit_logit(
    formula: str, data: pd.DataFrame, cluster: str | None = None, robust: bool = False
) -> LogitFit:
    """Fit a logistic regression (binomial GLM, logit link).

    With ``cluster``, standard errors are cluster-robust (sandwich) by that column, which
    allows observations within a cluster (e.g. the same seller) to be correlated. With
    ``robust`` (and no cluster), heteroskedasticity-robust HC1 standard errors are used,
    which stay valid if the logit functional form is misspecified.
    The data must already be complete: missing values raise instead of being silently
    dropped, so observation counts always match the documented population.
    """
    used = data.copy()
    model = smf.glm(formula, data=used, family=sm.families.Binomial(), missing="raise")
    if cluster:
        groups = pd.factorize(used[cluster])[0]
        result = model.fit(cov_type="cluster", cov_kwds={"groups": groups})
    elif robust:
        result = model.fit(cov_type="HC1")
    else:
        result = model.fit()
    return LogitFit(result, used, formula, cluster)


def tidy(fit: LogitFit, alpha: float = 0.05) -> pd.DataFrame:
    """Coefficient table with odds ratios and Wald confidence intervals."""
    res = fit.result
    ci = res.conf_int(alpha=alpha)
    out = pd.DataFrame(
        {
            "term": res.params.index,
            "coef": res.params.to_numpy(),
            "std_err": res.bse.to_numpy(),
            "z": res.tvalues.to_numpy(),
            "p_value": res.pvalues.to_numpy(),
            "ci_low": ci[0].to_numpy(),
            "ci_high": ci[1].to_numpy(),
        }
    )
    out["odds_ratio"] = np.exp(out["coef"])
    out["or_ci_low"] = np.exp(out["ci_low"])
    out["or_ci_high"] = np.exp(out["ci_high"])
    return out


def vif_table(fit: LogitFit) -> pd.DataFrame:
    """Variance inflation factor for every non-intercept column of the design matrix."""
    exog = pd.DataFrame(fit.result.model.exog, columns=fit.result.model.exog_names)
    values = exog.to_numpy(dtype=float)
    rows = [
        {"term": name, "vif": float(variance_inflation_factor(values, i))}
        for i, name in enumerate(exog.columns)
        if name != "Intercept"
    ]
    return pd.DataFrame(rows).sort_values("vif", ascending=False, ignore_index=True)


def roc_auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve via the Mann-Whitney rank statistic (ties averaged)."""
    y = np.asarray(y).astype(bool)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = stats.rankdata(p)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def performance(fit: LogitFit) -> dict[str, float]:
    """In-sample discrimination and calibration summaries (not evidence of causality)."""
    res = fit.result
    y = res.model.endog
    p = res.fittedvalues
    null = sm.GLM(y, np.ones_like(y), family=sm.families.Binomial()).fit()
    return {
        "n": int(res.nobs),
        "events": int(y.sum()),
        "event_rate": float(y.mean()),
        "parameters": len(res.params),
        "auc": roc_auc(y, p),
        "brier": float(np.mean((p - y) ** 2)),
        "brier_null": float(np.mean((y.mean() - y) ** 2)),
        "mcfadden_r2": float(1 - res.llf / null.llf),
        "aic": float(res.aic),
    }


def calibration_table(fit: LogitFit, bins: int = 10) -> pd.DataFrame:
    """Observed vs mean predicted probability by decile of predicted risk."""
    res = fit.result
    df = pd.DataFrame({"y": res.model.endog, "p": res.fittedvalues})
    df["bin"] = pd.qcut(df["p"].rank(method="first"), bins, labels=False) + 1
    out = df.groupby("bin").agg(n=("y", "size"), observed=("y", "mean"), predicted=("p", "mean"))
    return out.reset_index()


def _design(fit: LogitFit, frame: pd.DataFrame) -> np.ndarray:
    """Design matrix for new data using the fitted model's patsy design (same columns)."""
    data = fit.result.model.data
    # statsmodels >= 0.15 stores the patsy DesignInfo as ``model_spec``.
    design_info = getattr(data, "model_spec", None) or data.design_info
    return np.asarray(patsy.build_design_matrices([design_info], frame)[0], dtype=float)


def _draws(fit: LogitFit, n_draws: int, seed: int) -> np.ndarray:
    """Parameter draws from the asymptotic sampling distribution (uses the fit's covariance,
    so cluster-robust when the fit is clustered)."""
    rng = np.random.default_rng(seed)
    res = fit.result
    return rng.multivariate_normal(res.params.to_numpy(), res.cov_params().to_numpy(), size=n_draws)


def average_predictions(
    fit: LogitFit,
    variable: str,
    levels: list,
    subset: pd.Series | None = None,
    n_draws: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Average adjusted predictions: set ``variable`` to each level for every observation in
    ``subset`` (others keep their observed covariates) and average the predicted
    probability. Intervals come from simulating the coefficient distribution.
    """
    base = fit.data if subset is None else fit.data.loc[subset]
    params = fit.result.params.to_numpy()
    draws = _draws(fit, n_draws, seed)
    rows = []
    for level in levels:
        frame = base.copy()
        frame[variable] = level
        if isinstance(base[variable].dtype, pd.CategoricalDtype):
            frame[variable] = pd.Categorical(
                frame[variable], categories=base[variable].cat.categories
            )
        x = _design(fit, frame)
        point = float(np.mean(_sigmoid(x @ params)))
        sims = _sigmoid(x @ draws.T).mean(axis=0)
        lo, hi = np.quantile(sims, [alpha / 2, 1 - alpha / 2])
        rows.append({"level": level, "probability": point, "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows)


def average_marginal_effect(
    fit: LogitFit,
    variable: str,
    treated,
    reference,
    subset: pd.Series | None = None,
    n_draws: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Average difference in predicted probability, ``treated`` vs ``reference``.

    ``treated``/``reference`` are constants or callables applied to the observed column.

    This is a percentage-point quantity, unlike the odds ratio. It is averaged over the
    observations in ``subset`` with all other covariates at their observed values.
    """
    base = fit.data if subset is None else fit.data.loc[subset]
    params = fit.result.params.to_numpy()
    draws = _draws(fit, n_draws, seed)
    xs = {}
    for name, value in (("treated", treated), ("reference", reference)):
        frame = base.copy()
        # A callable maps observed values to counterfactual ones (e.g. x + 1).
        frame[variable] = value(frame[variable]) if callable(value) else value
        xs[name] = _design(fit, frame)
    diff_point = float(
        np.mean(_sigmoid(xs["treated"] @ params) - _sigmoid(xs["reference"] @ params))
    )
    diff_sims = (_sigmoid(xs["treated"] @ draws.T) - _sigmoid(xs["reference"] @ draws.T)).mean(
        axis=0
    )
    lo, hi = np.quantile(diff_sims, [alpha / 2, 1 - alpha / 2])
    # Delta method (exact, no Monte Carlo noise): gradient of the AME w.r.t. the
    # coefficients is mean(p1 (1 - p1) x1) - mean(p0 (1 - p0) x0).
    p1, p0 = _sigmoid(xs["treated"] @ params), _sigmoid(xs["reference"] @ params)
    grad = ((p1 * (1 - p1))[:, None] * xs["treated"]).mean(axis=0) - (
        (p0 * (1 - p0))[:, None] * xs["reference"]
    ).mean(axis=0)
    se = float(np.sqrt(grad @ fit.result.cov_params().to_numpy() @ grad))
    z = stats.norm.ppf(1 - alpha / 2)
    return {
        "ame": diff_point,
        "ame_ci_low": float(lo),
        "ame_ci_high": float(hi),
        "ame_se_delta": se,
        "ame_delta_ci_low": diff_point - z * se,
        "ame_delta_ci_high": diff_point + z * se,
        "n": len(base),
    }


def cooks_distance(fit: LogitFit) -> pd.Series:
    """Cook's distance for every observation of a fitted GLM."""
    cooks = fit.result.get_influence(observed=False).cooks_distance[0]
    return pd.Series(cooks, index=fit.data.index)


def influential_mask(fit: LogitFit, top_share: float = 0.01) -> pd.Series:
    """Flag the ``top_share`` most influential observations by Cook's distance.

    The textbook cut-off 4/n flags ~10% of a large logistic sample (most poorly fitted
    cases), which would change the population rather than test robustness; dropping a
    fixed top share is a more targeted check.
    """
    cooks = cooks_distance(fit)
    return cooks >= cooks.quantile(1 - top_share)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))
