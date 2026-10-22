-- SIMULATED DATA. Analysis dataset of the synthetic checkout experiment.
-- Grain: one row per (scenario, user_id) for every user with at least one checkout
-- exposure (= assigned). The denominator of every per-user metric is this table.
--
-- Users are never dropped here: assignment or outcome problems (a user seen in both
-- variants, missing outcomes) stay visible and are caught by sql/quality_checks/sim_*.
CREATE OR REPLACE TABLE sim.fct_experiment_users AS
WITH exposures AS (
    SELECT
        scenario,
        user_id,
        min(exposed_at)            AS first_exposed_at,
        count(*)                   AS exposures,
        count(DISTINCT variant)    AS distinct_variants,
        arg_min(variant, exposed_at) AS variant   -- variant at first exposure
    FROM sim.assignment_events
    GROUP BY scenario, user_id
)
SELECT
    e.scenario,
    e.user_id,
    e.variant,
    e.distinct_variants,
    e.first_exposed_at,
    CAST(e.first_exposed_at AS DATE)                        AS exposure_date,
    e.exposures,
    u.device,
    u.customer_type,
    o.purchased,
    o.order_value,
    o.order_cancelled,
    o.checkout_error,
    o.checkout_seconds,
    coalesce(o.purchased AND o.order_cancelled, FALSE)      AS cancelled_order,
    -- Net order value per assigned user: value of a purchase that was not cancelled,
    -- 0 for everyone else (so the mean is over ALL assigned users).
    CASE WHEN o.purchased AND NOT o.order_cancelled THEN o.order_value ELSE 0 END
                                                            AS net_order_value
FROM exposures AS e
LEFT JOIN sim.users AS u    USING (scenario, user_id)
LEFT JOIN sim.outcomes AS o USING (scenario, user_id);
