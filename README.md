# Marketplace Checkout & Experimentation Lab

The project asks whether a simplified checkout experience would improve purchase
completion without hurting order value or other customer and operational metrics.

It has two strictly separated parts:

1. **Historical analysis of real data** from the
   [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
   (orders, payments, delivery, reviews).
2. **A SIMULATED checkout A/B experiment**, used to demonstrate experiment design and
   analysis. Olist contains no sessions, checkout attempts or experiment assignments,
   so no real conversion rate or real treatment effect is reported anywhere in this
   repository.

## Quickstart

```bash
uv sync                                         # install dependencies
uv run python -m marketplace_analytics download # fetch Olist CSVs into data/raw/
uv run python -m marketplace_analytics build    # build DuckDB warehouse + quality checks
uv run python -m marketplace_analytics eda      # reconcile Python vs SQL, EDA charts + tables
uv run python -m marketplace_analytics regression  # observational low-review regression
uv run python -m marketplace_analytics experiment  # SIMULATED checkout A/B test (sim schema)
uv run python -m marketplace_analytics experiment-regression  # logistic regression of the SIMULATED test
uv run python -m marketplace_analytics export-powerbi  # Parquet files for the Power BI model (powerbi/data/)
uv run python -m marketplace_analytics powerbi-report  # regenerate the PBIR report pages
uv run pytest                                   # tests (use a fixture, no real data needed)
uv run ruff check . && uv run ruff format --check .
```

Historical findings: [reports/eda_findings.md](reports/eda_findings.md) and
[reports/regression_findings.md](reports/regression_findings.md) (observational).
SIMULATED experiment: [docs/experiment_plan.md](docs/experiment_plan.md) (pre-registration)
and [reports/experiment_findings.md](reports/experiment_findings.md), with regression in
[reports/experiment_regression_findings.md](reports/experiment_regression_findings.md).
Power BI report (4 pages, real and SIMULATED kept apart): [powerbi/README.md](powerbi/README.md).
Methods: [docs/methodology.md](docs/methodology.md).
See [data/README.md](data/README.md), [docs/architecture.md](docs/architecture.md)
and [docs/data_dictionary.md](docs/data_dictionary.md).
