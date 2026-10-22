-- description: Assignments, user attributes and outcomes cover exactly the same SIMULATED users.
-- severity: error
SELECT 'assigned without user attributes' AS issue, scenario, user_id
FROM sim.fct_experiment_users WHERE device IS NULL OR customer_type IS NULL
UNION ALL
SELECT 'assigned without outcome', scenario, user_id
FROM sim.fct_experiment_users WHERE purchased IS NULL OR checkout_error IS NULL
UNION ALL
SELECT 'outcome without assignment', o.scenario, o.user_id
FROM sim.outcomes AS o
LEFT JOIN sim.fct_experiment_users AS f USING (scenario, user_id)
WHERE f.user_id IS NULL
UNION ALL
SELECT 'user never exposed', u.scenario, u.user_id
FROM sim.users AS u
LEFT JOIN sim.fct_experiment_users AS f USING (scenario, user_id)
WHERE f.user_id IS NULL;
