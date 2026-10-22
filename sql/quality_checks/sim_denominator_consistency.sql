-- description: SIMULATED variant summaries use the assigned-user denominator and reconcile with the user-level table.
-- severity: error
WITH fct AS (
    SELECT scenario, variant, count(*) AS users, count(*) FILTER (WHERE purchased) AS buyers
    FROM sim.fct_experiment_users GROUP BY scenario, variant
)
SELECT a.scenario, a.variant, a.assigned_users, f.users, a.purchasers, f.buyers
FROM sim.agg_variant_metrics AS a
FULL OUTER JOIN fct AS f USING (scenario, variant)
WHERE a.assigned_users IS DISTINCT FROM f.users
   OR a.purchasers IS DISTINCT FROM f.buyers
   OR a.purchasers > a.assigned_users
   OR abs(a.purchase_completion_rate - a.purchasers / a.assigned_users) > 1e-12
UNION ALL
SELECT d.scenario, d.variant, sum(d.new_users), NULL, NULL, NULL
FROM sim.daily_assignments AS d
GROUP BY d.scenario, d.variant
HAVING sum(d.new_users) <> (
    SELECT count(*) FROM sim.fct_experiment_users AS f
    WHERE f.scenario = d.scenario AND f.variant = d.variant
);
