# Architecture

```
              REAL DATA                                   SIMULATED DATA
  ┌────────────────────────────┐              ┌──────────────────────────────────┐
  │ Kaggle: Olist CSVs         │              │ config/settings.yaml (seed,      │
  │ data/raw/*.csv             │              │ scenario parameters)             │
  └─────────────┬──────────────┘              └────────────────┬─────────────────┘
                │ download / build                             │ simulate
                ▼                                              ▼
  ┌────────────────────────────┐              ┌──────────────────────────────────┐
  │ DuckDB  raw.*   (VARCHAR)  │              │ DuckDB  sim.*  (SIMULATED)       │
  │         stg.*   (typed)    │              │ users, assignments, outcomes     │
  │         olist.* (marts)    │              │ true parameters kept separately  │
  └─────────────┬──────────────┘              └────────────────┬─────────────────┘
                │ sql/quality_checks/olist_*                   │ sql/quality_checks/sim_*
                ▼                                              ▼
  ┌────────────────────────────┐              ┌──────────────────────────────────┐
  │ Python: EDA, observational │              │ Python: A/B analysis, power,     │
  │ regression (statsmodels)   │              │ SRM, logistic regression         │
  └─────────────┬──────────────┘              └────────────────┬─────────────────┘
                └───────────────┬──────────────────────────────┘
                                ▼
              reports/ (figures, results)   powerbi/ (PBIP report + semantic model)
```

## Design decisions

- **DuckDB with plain SQL files instead of dbt.** The SQL lives in `sql/` as one file
  per model, run in name order by `data/warehouse.py`. A quality check is a SELECT that
  returns the rows breaking a rule (the same idea as a dbt singular test), with
  `-- severity: error|warn` in its header. This keeps the project to one runtime with
  no Jinja and no profiles. Moving to dbt-duckdb later would be mechanical: each file
  becomes a model and each check becomes a test.
- **Raw is loaded as all-VARCHAR, and staging casts explicitly.** Type inference never
  silently changes data (for example, ZIP prefixes with leading zeros stay text). A bad
  value makes the cast in staging fail with an error that points at the file.
- **Real and simulated data are kept apart.** Historical marts live in the `olist`
  schema and simulated tables in `sim`. No SQL file reads from both, and every `sim`
  table name and every dashboard element showing simulated data is labelled SIMULATED.
- **Aggregate before joining.** `fct_orders` aggregates items, payments and reviews to
  the order grain in separate CTEs and only then joins them, so totals cannot fan out.
  `olist_reconcile_totals` checks this on every build.
- **Power BI reads exported Parquet, not DuckDB.** Desktop has no built-in DuckDB
  connector, and an ODBC driver would be one more thing to install. `export-powerbi`
  writes one Parquet file per model table, and the model imports them. The report
  pages are generated from code so that layout is reviewable in diffs and
  reproducible.
- **Configuration comes from one place.** Analysis window, low-review threshold, seeds
  and simulation scenarios are read from `config/settings.yaml`. SQL receives them as
  DuckDB session variables (`getvariable('analysis_start')`).

## Code layout

| Path | Responsibility |
|---|---|
| `src/marketplace_analytics/config.py` | Load settings and resolve paths |
| `src/marketplace_analytics/data/` | Download, raw load, SQL runner, quality checks |
| `src/marketplace_analytics/metrics/` | Python metric implementations (used to cross-check SQL) |
| `src/marketplace_analytics/statistics/` | Hypothesis tests, CIs, power, regression helpers |
| `src/marketplace_analytics/experiments/` | SIMULATED experiment generator and analysis |
| `src/marketplace_analytics/reporting/` | Charts and result tables |
| `sql/staging`, `sql/marts`, `sql/quality_checks` | Warehouse transformations and tests |
| `sql/analysis` | Read-only EDA and investigation queries (`eda_*`, `inv_*`) |
| `sql/models` | Candidate rows for statistical models (eligibility applied and counted in Python) |
| `sql/sim` | SIMULATED experiment: user-level fact, variant summaries, daily assignments |
| `sql/powerbi` | One query per Power BI table: `hist_*` from `olist`, `sim_*` from `sim` |
| `powerbi/` | PBIP: TMDL semantic model, generated PBIR report, Desktop screenshots ([powerbi/README.md](../powerbi/README.md)) |
| `reports/results`, `reports/figures` | Generated tables and charts (small aggregates, committed) |
| `tests/` | Unit and integration tests (run on a small fixture, never on real data) |
