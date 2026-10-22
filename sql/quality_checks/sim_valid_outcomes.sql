-- description: SIMULATED outcomes are internally consistent (purchase-only fields present iff purchased, positive values).
-- severity: error
SELECT scenario, user_id, 'order_value present iff purchased' AS rule
FROM sim.fct_experiment_users WHERE purchased <> (order_value IS NOT NULL)
UNION ALL
SELECT scenario, user_id, 'checkout_seconds present iff purchased'
FROM sim.fct_experiment_users WHERE purchased <> (checkout_seconds IS NOT NULL)
UNION ALL
SELECT scenario, user_id, 'order_cancelled present iff purchased'
FROM sim.fct_experiment_users WHERE purchased <> (order_cancelled IS NOT NULL)
UNION ALL
SELECT scenario, user_id, 'order_value must be > 0'
FROM sim.fct_experiment_users WHERE order_value <= 0
UNION ALL
SELECT scenario, user_id, 'checkout_seconds must be > 0'
FROM sim.fct_experiment_users WHERE checkout_seconds <= 0
UNION ALL
SELECT scenario, user_id, 'net_order_value must be >= 0'
FROM sim.fct_experiment_users WHERE net_order_value < 0 OR net_order_value IS NULL;
