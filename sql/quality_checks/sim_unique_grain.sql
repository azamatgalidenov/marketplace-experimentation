-- description: SIMULATED experiment tables are unique at their grain (no duplicate users or outcomes).
-- severity: error
SELECT 'fct_experiment_users' AS model, scenario, user_id, count(*) AS n
FROM sim.fct_experiment_users GROUP BY scenario, user_id HAVING count(*) > 1
UNION ALL
SELECT 'users', scenario, user_id, count(*)
FROM sim.users GROUP BY scenario, user_id HAVING count(*) > 1
UNION ALL
SELECT 'outcomes', scenario, user_id, count(*)
FROM sim.outcomes GROUP BY scenario, user_id HAVING count(*) > 1;
