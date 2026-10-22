-- Power BI export: SIMULATED metric-level results (Python-computed inference). Grain: scenario + metric.
SELECT scenario, metric, role,
       CASE metric WHEN 'purchase_completion' THEN 1 WHEN 'net_order_value_per_user' THEN 2
            WHEN 'checkout_error_rate' THEN 3 WHEN 'cancellation_rate' THEN 4
            WHEN 'aov_purchasers' THEN 5 ELSE 6 END AS metric_order,
       metric_type, n_treatment, n_control, value_control, value_treatment, abs_diff, abs_ci_low, abs_ci_high,
       rel_diff, rel_ci_low, rel_ci_high, p_value, margin, margin_scale,
       coalesce(guardrail_status, CASE role WHEN 'primary' THEN 'primary' ELSE 'descriptive' END) AS guardrail_status
FROM sim.metric_results
