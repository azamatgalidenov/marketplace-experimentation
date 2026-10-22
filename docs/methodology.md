# Methodology

This project uses two kinds of evidence, and they must not be confused:

| | Historical analysis (Phases A–B) | Checkout experiment (Phases C–D) |
|---|---|---|
| Data | Real Olist orders | **SIMULATED** users (synthetic) |
| Design | Observational | Randomised (in simulation) |
| What it can show | Descriptions and **associations** | How to estimate and judge a treatment effect |
| What it cannot show | Causal effects | Anything about the real business |

---

## Part 1: Observational regression on low reviews (Phase B)

Code: `statistics/low_review_model.py` (population, features, specifications),
`statistics/regression.py` (generic estimation helpers), `reporting/regression.py`
(pipeline and outputs), `sql/models/low_review_candidates.sql`.
Run: `uv run python -m marketplace_analytics regression`.

### 1.1 Question and outcome

> Which observable order, delivery, product and geographic factors are **associated**
> with a customer leaving a low review?

**Low review** means `review_score <= 2`, set by `olist.low_review_max_score`.

- Scores are bimodal: 1 star is 11.5% of reviews, 5 stars 57.8%, and 3 stars only
  8.2%. Scores 1–2 are unambiguously negative.
- A score of 3 is closer to neutral. Including it is tested as a sensitivity (A2).
- A binary outcome keeps the business reading simple ("share of dissatisfied
  customers"). The cost is discarding the gap between 1 and 2 stars.

### 1.2 Population and grain

One row per order, using the documented latest-review rule (`fct_orders`). Rules are
applied in order, and the counts are written to `population_funnel.csv`:

1. Purchased in the analysis window (2017-01-01 to 2018-08-31).
2. Delivered with a customer-delivery timestamp (*measurable*).
3. Has a review.
4. Survey sent and answered on or after the purchase (drops source inconsistencies).

There is no imputation. Every model field is complete in the eligible population
(`missingness.csv`). Products without a category stay as an explicit `unknown` level.

### 1.3 Dates and survey timing

| Field | Meaning | Precision |
|---|---|---|
| `review_survey_sent_date` (source `review_creation_date`) | Date the satisfaction **survey was sent** | Day |
| `review_answered_at` | When the customer **answered** | Timestamp |
| `delivered_to_customer_at` | Recorded delivery to customer | Timestamp |
| `estimated_delivery_date` | Promised delivery date | Day |

The flag `reviewed_before_delivery` from Milestone 1 was **wrong**: it treated the
survey-sent date as the review date. It has been replaced.

**Primary timing classification** (`classify_survey_timing`, rule `sent_date`)
compares calendar dates:

- `pre`: survey sent before the delivery date.
- `same_day`: sent on the delivery date. Kept separate because a date-only field
  cannot order two events within one day.
- `post`: sent after the delivery date.

**Alternative** (rule `answered`): the answer timestamp compared with the delivery
timestamp.

**Why timing must be modelled.** Late orders usually get their survey before they
arrive. In the data, 2,778 of the 2,779 orders delivered 8+ days late had a
pre-delivery survey. Severe lateness and pre-delivery surveying are therefore almost
perfectly confounded, and no specification can separate them. Survey timing is also
partly a **consequence** of lateness: surveys appear to be triggered when the promised
date passes. So conditioning on timing removes a measurement pathway (rating an order
not yet received). It is not a classic confounder adjustment.

### 1.4 Predictors

| Variable | Definition | Reference / unit |
|---|---|---|
| `late` | Delivery calendar date > promised date | On time |
| survey timing | `pre` / `same_day` / `post` (above) | `post` |
| `promised_weeks` | (promised date − purchase date) / 7 | +1 week |
| `log_items_value` | ln(Σ item prices) | ×e (≈ ×2.72); AME reported for ×2 |
| `freight_share_10pp` | freight / (items + freight) × 10 | +10 percentage points |
| basket | single item / several items from one seller / several sellers | single item |
| category | 15 most frequent primary categories, `unknown`, rest pooled as `other` | Most frequent (bed_bath_table) |
| region | Customer IBGE macro-region | Southeast |
| month | Purchase year-month (fixed effects) | Most frequent month (2017-11) |

**Excluded on purpose:**

- *Actual delivery duration*, because it equals promised days + delay and would be
  redundant with `late` and `promised_weeks`.
- *Review comment flag and review count*, because they are produced by the review
  itself (leakage).
- *Payment method*, which has no clear mechanism and isn't needed for the question.

### 1.5 Specifications

| Spec | Sample | Model | Purpose |
|---|---|---|---|
| M1 | Full | low ~ late | Unadjusted baseline |
| M2 | Full | low ~ late × timing | Separates the timing pathway |
| **M3** | Full | M2 + covariates | **Primary** full-sample model |
| M4 | `post` only | low ~ late | Restricted, unadjusted |
| **M5** | `post` only | late + covariates | **Primary** restricted model |
| T1 | `post` + `same_day` | as M5 | Timing threshold |
| T2 | Answered after delivery | as M5 | Answer-based restriction |
| T3 | Full | late × answer-timing + covariates | Answer-based timing |
| T4 | Full minus unexplained early surveys | reparametrised M3 | Date-anomaly exclusion |
| A1 | Full | M3 with timestamp-level lateness | Lateness definition |
| A2 | Full | M3 with score ≤ 3 | Outcome threshold |
| A3 | Single-review orders | M3 | Review-selection rule |
| A4 | Minus the 20 sellers with most late `post` orders | M3 | Concentration in few sellers |
| CELLS | Full | delay category × timing cells + covariates | What the data can and cannot separate |

In M2/M3 the `late` coefficient is the late-vs-on-time association **for orders
surveyed after delivery**. Associations within the other timing groups are linear
combinations (`late_or_by_timing_M3.csv`).

Final specifications were fixed **before** looking at which gave the smallest p-value.
The one later change was A4. It originally removed the top 1% of observations by
Cook's distance. That proved circular (§1.7), so it was moved to a diagnostic and
replaced by the seller-concentration check.

### 1.6 Estimation and uncertainty

- **Logistic regression** (binomial GLM, logit link) in `statsmodels`.
- **Standard errors are cluster-robust by primary seller** (2,931 clusters), because
  orders from the same seller share operations and are not independent. Model-based
  and cluster SEs are compared in `standard_errors_M3.csv`. Repeat customers (about 3%
  of orders) are a second, unmodelled source of dependence.
- **Odds ratio vs percentage points.** An odds ratio multiplies the *odds* p/(1−p),
  not the probability. With a 9% baseline, OR 2.4 moves the probability from about 9%
  to about 19%, i.e. +10 percentage points (not "+140%"). Every key effect is therefore
  also reported as an **average marginal effect (AME)**. To compute one, set the
  variable to each value for every observation, keep the other covariates as observed,
  and average the difference in predicted probability.
- **AME and prediction intervals** come from 1,000 draws of the coefficient vector
  from its (cluster-robust) sampling distribution.
- **Cross-check without a model:** Cochran–Mantel–Haenszel tests of late vs low
  review, stratified by region and by month, with Breslow–Day homogeneity tests.

### 1.7 Diagnostics

- **Multicollinearity.** VIF on the design matrix. High VIFs appear only for the
  timing × late terms, which is structural to an interaction with a rare cell. The
  covariates stay below 4.
- **Calibration and discrimination.** In-sample decile calibration, AUC, Brier score
  and McFadden R². These describe fit and are **not evidence of causality**. With
  about 50 parameters and about 90k rows, overfitting is negligible, so no hold-out
  set is used.
- **Influence.** Cook's distance. The 4/n rule flags about 10% of observations. The
  top 1% contains most of the late/post/low-review cases, so deleting them removes the
  association being studied. This is reported as a fragility diagnostic, not used as a
  robustness specification.

### 1.8 What this analysis cannot do

- **No causal claim.** Lateness is not randomised. Sellers, carriers, routes,
  products and seasons differ between late and on-time orders, and only some of that
  is observed.
- **Selection into the sample.** Only reviewed, delivered orders are modelled, and
  answering a survey is voluntary.
- **Selection by restriction.** The `post` subset keeps late orders that were
  surveyed after arrival, which are almost all only 1–7 days late. Its estimate
  describes **mild** lateness and does not generalise to severe delays. The
  restriction is not "unbiased" just because the survey followed delivery.
- **Measurement.** Delivery is recorded per order, not per item or shipment. The
  survey trigger rule is inferred, not documented.

---

## Part 2: Simulated checkout experiment (Phases C–D)

The full pre-registered design is in [experiment_plan.md](experiment_plan.md), and the
results are in [reports/experiment_findings.md](../reports/experiment_findings.md).
Run: `uv run python -m marketplace_analytics experiment`.

### 2.1 Why simulate

Olist records completed orders only. It has no checkout visits, abandoned checkouts or
randomised assignments, so no conversion rate or treatment effect can be estimated from
it. The experiment is therefore generated synthetically, from explicit assumptions, to
demonstrate design and analysis. Its outputs are labelled SIMULATED everywhere.

### 2.2 Separation of truth and analysis

| Layer | Contents | Who reads it |
|---|---|---|
| `config/settings.yaml` → `experiment.scenarios` | True effects per scenario | Simulator, validation |
| `sim.users`, `sim.assignment_events`, `sim.outcomes` | Observed synthetic data | SQL layer |
| `sim.fct_experiment_users` (SQL) | Analysis dataset, one row per assigned user | Analysis |
| `sim.simulation_truth_validation_only` | True parameters per scenario | Validation and documentation only |

`experiments/analysis.py` takes only the analysis dataset and the design (α, margins,
thresholds). A test confirms that permuting the observed outcomes changes the estimate
while the scenario parameters stay the same.

### 2.3 Statistical methods

- **Primary.** Pooled two-proportion z-test for H0: p_T = p_C. The 95% Newcombe
  (hybrid Wilson score) CI for p_T − p_C is cross-checked against statsmodels.
  Relative lift CI by the delta method on the log risk ratio.
- **Continuous metrics.** Welch's t-test with unequal variances. Relative CI by the
  delta method for a ratio of means. Checkout time is compared on the log scale, as a
  ratio of geometric means.
- **SRM.** Chi-square goodness of fit against the planned split, with α = 0.001.
- **Power and MDE.** statsmodels `NormalIndPower` on Cohen's h, checked against the
  closed-form two-proportion formula. MDE is solved numerically. Guardrail
  non-inferiority sample sizes use n = 2(z₀.₉₇₅ + z₀.₈)²σ²/margin².
- **Segments.** Per-level tests with Benjamini–Hochberg FDR adjustment, a per-segment
  MDE and small-sample flags.

### 2.4 Key concepts as used here

- **p-value.** The probability, if the treatment had no effect, of a difference at
  least as extreme as the one observed. It is not the probability that the treatment
  works.
- **Confidence interval.** A range built by a procedure that captures the true
  difference in 95% of repeated experiments. Validation checks exactly this coverage.
- **Type I error (false positive).** Declaring an effect when there is none. It is held
  at α = 5% for the primary metric, and the A/A and null validations measure it.
- **Type II error (false negative).** Missing a real effect. Its probability is 1 −
  power: about 20% at the MDE, and about 79% for the 0.8 pp small-effect scenario.
- **Statistical power.** The probability of detecting a true effect of a given size.
  It is fixed by the sample, the baseline and α, not by the result.
- **Practical significance.** Whether the effect is large enough to matter. Here the
  threshold is ≥ +1.0 pp. A significant +0.3 pp would still be rejected.
- **A non-significant result is not proof of no effect.** It is inconclusive unless its
  CI excludes every effect large enough to matter.

### 2.5 Validation by repeated simulation

`experiments/validation.py` reruns the full simulator and the analysis 500 times per
scenario, with fresh users and fresh hash salts. It then compares the following against
their expected values, using 99% binomial tolerance intervals:

- false-positive rate under A/A and null (expected: α),
- rejection rate under positive and small effects (expected: analytic power),
- 95% CI coverage of the true effect,
- SRM false alarms and SRM detection at 1–10% treatment logging loss (expected:
  noncentral chi-square power).

The pytest suite repeats these checks with a 99.9% tolerance, so the tests are not
brittle exact-number comparisons.

### 2.6 Regression analysis of the experiment (Phase D)

Code: `experiments/regression.py` and `reporting/experiment_regression.py`. Run:
`uv run python -m marketplace_analytics experiment-regression`. Results are in
[reports/experiment_regression_findings.md](../reports/experiment_regression_findings.md).

- **Why adjust at all.** Randomisation already makes the unadjusted difference
  unbiased. Adding *pre-treatment* covariates that predict the outcome removes some
  noise and narrows the confidence interval. It does not change what is being
  estimated. Covariates measured *after* assignment can be moved by the treatment.
  Adjusting for them removes part of the effect itself (a mediator) or creates
  selection bias, so they are excluded. `mediator_bias_demo` shows this on a labelled
  toy simulation.
- **Odds ratio vs percentage points.** The logit coefficient gives a *conditional* odds
  ratio, which multiplies the odds p/(1−p). The same +2.5 pp effect has a different
  odds ratio at a 38% baseline than at a 64% baseline. Product decisions need the
  **average marginal effect**: the mean change in predicted purchase probability when
  every user is switched from control to treatment, in percentage points.
- **Unadjusted vs adjusted.** The unadjusted logit is saturated (one binary
  regressor), so its AME equals the raw difference exactly. The pipeline enforces
  this. The adjusted AME should be close to the raw difference, with an interval that
  is equal or narrower.
- **Interaction on which scale.** "No interaction" on the probability scale (the
  simulation adds a constant number of pp) is not the same as "no interaction" on the
  log-odds scale. With baselines between 38% and 64% the difference is small, but
  heterogeneity claims always need the scale stated.
- **Misspecification.** The simulation is additive in probabilities, not logistic, so
  the logit is an approximation. HC1 robust standard errors and AMEs keep the treatment
  estimate valid. The repeated-simulation check confirms its coverage and false-positive
  rate.

