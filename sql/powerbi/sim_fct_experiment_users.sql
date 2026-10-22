-- Power BI export: SIMULATED experiment analysis dataset. Grain: scenario + user_id.
SELECT scenario, user_id, variant, exposure_date, device, customer_type, purchased,
       order_value, checkout_error, checkout_seconds, cancelled_order, net_order_value
FROM sim.fct_experiment_users
