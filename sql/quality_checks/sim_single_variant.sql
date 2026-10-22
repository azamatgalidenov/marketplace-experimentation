-- description: Every SIMULATED user is exposed to exactly one variant (stable assignment, no cross-over).
-- severity: error
SELECT scenario, user_id, distinct_variants
FROM sim.fct_experiment_users
WHERE distinct_variants <> 1
   OR variant NOT IN ('control', 'treatment')
   OR variant IS NULL;
