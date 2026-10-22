# Experiment plan: simplified checkout (SIMULATED)

> **This is a simulated experiment.** No real users, sessions, checkouts or
> assignments exist. Olist contains none of these, so the data is synthetic and
> generated from the assumptions below. The plan shows how such a test would be
> designed and pre-registered. Its numbers are **not** estimates of any real company's
> checkout performance.
>
> All parameters live in `config/settings.yaml` (`experiment:`) and were fixed before
> any simulated outcome was analysed.

## 1. Hypothesis

Replacing the existing checkout with a **simplified checkout** (fewer steps and
fields) will **increase the share of checkout-entering users who complete a purchase
within 7 days by at least 2 percentage points** (planning baseline 55%, target ≥ 57%).
The proposed mechanism is less friction and fewer errors for users who already intend
to buy.

**Falsification.** The plan does **not** launch if:

- the primary metric does not improve with confidence,
- any guardrail shows harm beyond its margin, or
- the plausible lift is too small to matter (< 1 pp).

## 2. Population, unit and assignment

| Item | Definition |
|---|---|
| Experimental unit | User (`user_id`) |
| Eligibility | A user who **opens the checkout** at least once during the 14-day test window. Eligibility is triggered at the first checkout visit. |
| Assignment | `variant = treatment` if `SHA-256(salt + ':' + user_id)` mapped to [0, 1) is < 0.5, else `control`. The hash is **deterministic**, so a user sees the same variant on every visit and device. The split is 50/50. |
| Denominator | **All assigned users** (intention-to-treat). Users are never dropped for not purchasing, erroring or having multiple visits. |
| Duration | 14 days (two full weekly cycles) at an assumed 1,500 eligible users per day, giving 21,000 users. |
| Segments (pre-registered) | `device` (mobile_app, mobile_web, desktop) and `customer_type` (new, returning). Exploratory only. |

Per-user metrics never mix session-level and user-level denominators. Repeat checkout
visits (exposures) are kept in `sim.assignment_events`, but every metric is computed
once per user.

## 3. Metrics

| Role | Metric | Definition (per assigned user unless stated) | Test |
|---|---|---|---|
| **Primary** | Purchase completion | Share of assigned users with ≥ 1 purchase within 7 days of first exposure | Pooled two-proportion z-test, two-sided, α = 0.05; Newcombe 95% CI for the difference |
| Guardrail | Net order value per user | Value of non-cancelled purchases ÷ assigned users (0 for non-buyers) | Welch t; relative CI by delta method. Margin: ≤ 2% relative drop |
| Guardrail | Checkout error rate | Share of assigned users with ≥ 1 checkout error | Newcombe CI. Margin: ≤ +0.5 pp |
| Guardrail | Cancellation rate | Share of assigned users who purchased and then cancelled | Newcombe CI. Margin: ≤ +0.5 pp |
| Secondary | AOV among purchasers | Mean order value of buyers | Welch t, **descriptive** |
| Secondary | Checkout time among purchasers | Geometric mean of checkout seconds of buyers | Welch t on log seconds, **descriptive** |

**Why the two secondary metrics are descriptive only.** They are computed on buyers,
and buying is itself affected by the treatment. A treatment that converts extra,
lower-value buyers lowers AOV without harming anyone. Revenue per *assigned* user is
the randomised comparison, so it is the guardrail.

**Guardrail status** compares the 95% CI with the margin:

- **green**: deterioration beyond the margin is ruled out (non-inferiority shown).
- **red**: a statistically significant deterioration that is not shown to be within
  the margin.
- **amber**: neither. The data cannot rule out harm beyond the margin.

"Not significantly worse" is never read as "safe".

## 4. Sample size and power

- Planning baseline 55%, MDE +2.0 pp, α = 0.05 (two-sided), power 80%: **9,669 users
  per arm**. statsmodels `NormalIndPower` on Cohen's h agrees with the closed-form
  formula.
- The planned 10,500 per arm gives an **MDE of 1.92 pp**.
- The **practical threshold** is +1.0 pp, the smallest lift worth launching. Effects
  between 1 and 2 pp are worthwhile but are not reliably detected by this test.

## 5. Multiple testing and analysis discipline

- **One primary test** at α = 0.05, with no correction needed.
- **Guardrails** are each checked at 95% with no correction. Correcting would widen
  the intervals and make harm *harder* to detect, the wrong direction for a safety
  check.
- **Segments** are exploratory, with Benjamini–Hochberg-adjusted p-values. A segment
  is flagged as small if it has < 1,000 users per arm. Segment results never justify a
  segment-only launch.
- **Fixed horizon.** One analysis after 14 days and no interim peeking. Sequential
  testing is out of scope.
- **Sample-ratio mismatch.** A chi-square test against 50/50 runs first. If
  p < 0.001, the result is **INVALID** and is not interpreted.

## 6. Decision rules (applied mechanically, in this order)

1. **SRM detected**: INVALID, investigate assignment and logging.
2. **Any guardrail red**: REJECT.
3. **Primary CI entirely below 0**: REJECT.
4. **Primary CI lower bound > 0 and estimate ≥ 1.0 pp**:
   - all guardrails green: **LAUNCH**;
   - any guardrail amber: **CONTINUE TESTING** (guardrail unresolved).
5. **Primary CI upper bound < 1.0 pp**: REJECT (any effect is too small to justify
   launch).
6. **Otherwise**: **CONTINUE TESTING** (inconclusive). "Continue" means a *new*,
   pre-registered test sized for the smallest worthwhile effect, not extending this one
   after looking at it.

The A/A scenario is a system check, not a product decision. It passes when the primary
test is not significant and no SRM is detected.

## 6a. Secondary analysis: regression (added later, not decision-making)

This section was added in Milestone 5, **after** the primary results in section 6 were
known. It is therefore a secondary robustness analysis, **not** part of the
pre-registration, and it cannot change any decision. The device segment it examines
was pre-registered. The regression analysis checks robustness and precision, and runs
per scenario:

| Model | Formula | Purpose |
|---|---|---|
| Unadjusted | `purchased ~ treatment` | Must reproduce the raw difference exactly |
| Adjusted | `+ device + customer_type` | Precision gain from pre-treatment covariates |
| Interaction | `treatment × device + customer_type` | Heterogeneity across the pre-registered device segment (likelihood-ratio test, 2 df) |

- **Reference levels:** `mobile_app` and `returning`.
- **Standard errors:** HC1 robust.
- **Treatment effect:** reported both as an odds ratio and as an average marginal
  effect (percentage points, simulation intervals).
- **Excluded from adjustment:** checkout errors, checkout time, order value and
  cancellations. All of these happen after assignment and may be caused by the
  treatment.
- **No override:** a significant adjusted estimate cannot overturn an inconclusive
  primary result.

## 7. Data-generating assumptions (simulation only)

| Assumption | Value | Source |
|---|---|---|
| Device mix | app 50%, mobile web 30%, desktop 20% | Assumed |
| New customers | 40% | Assumed |
| Control purchase completion | 38–64% by device × customer type (about 54.6% overall) | Assumed |
| Checkout error rate | 4–9% by device | Assumed |
| Cancellation among buyers | 3% | Assumed |
| Order value | Log-normal, median 105, mean ≈ 160 | Shape borrowed from Olist delivered orders (median R$105, mean R$160) |
| Checkout time | Log-normal, median 150–210 s by device | Assumed |
| Visits per user | 1 (60%), 2 (25%), 3 (15%) | Assumed |

The outcomes are independent given device and customer type: errors do not cause
abandonment in the simulation. The treatment effects are scenario inputs (§8) and are
stored only in `sim.simulation_truth_validation_only`. The analysis never reads them.

## 8. Scenarios

| Scenario | True effect on treatment |
|---|---|
| `aa` | None. Both arms get the existing checkout. |
| `null_effect` | No change in purchase completion. Checkout is 10% faster. |
| `positive` | +2.5 pp completion, −1 pp errors, 15% faster |
| `small_effect` | +0.8 pp completion (below the MDE), 10% faster |
| `guardrail_harm` | +3 pp completion, +1.5 pp cancellations among buyers, 3% smaller orders, 15% faster |
