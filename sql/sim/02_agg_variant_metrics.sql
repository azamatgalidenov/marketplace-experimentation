-- SIMULATED DATA. Per-scenario, per-variant metric summary (no inference).
-- Denominator for per-user metrics = assigned users in sim.fct_experiment_users.
-- Used by the Python cross-check and by the Power BI report.
CREATE OR REPLACE TABLE sim.agg_variant_metrics AS
SELECT
    scenario,
    variant,
    count(*)                                              AS assigned_users,
    count(*) FILTER (WHERE purchased)                     AS purchasers,
    avg(CAST(purchased AS DOUBLE))                        AS purchase_completion_rate,
    avg(net_order_value)                                  AS net_order_value_per_user,
    avg(CAST(checkout_error AS DOUBLE))                   AS checkout_error_rate,
    avg(CAST(cancelled_order AS DOUBLE))                  AS cancellation_rate,
    avg(order_value) FILTER (WHERE purchased)             AS aov_purchasers,
    exp(avg(ln(checkout_seconds)) FILTER (WHERE purchased)) AS geomean_checkout_seconds
FROM sim.fct_experiment_users
GROUP BY scenario, variant
ORDER BY scenario, variant;
