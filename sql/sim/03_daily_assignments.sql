-- SIMULATED DATA. Daily new assignments per variant (for allocation-drift monitoring
-- and the Power BI diagnostics page).
CREATE OR REPLACE TABLE sim.daily_assignments AS
SELECT
    scenario,
    exposure_date,
    variant,
    count(*) AS new_users
FROM sim.fct_experiment_users
GROUP BY scenario, exposure_date, variant
ORDER BY scenario, exposure_date, variant;
