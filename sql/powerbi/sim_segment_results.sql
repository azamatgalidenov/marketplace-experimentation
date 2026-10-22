-- Power BI export: SIMULATED pre-registered segment results (exploratory). Grain: scenario + segment + level.
SELECT scenario, segment, level, segment || ': ' || level AS segment_label,
       row_number() OVER (PARTITION BY scenario ORDER BY segment, level) AS segment_order,
       n_treatment, n_control, value_control, value_treatment, abs_diff, abs_ci_low, abs_ci_high,
       p_value, p_value_bh, significant_after_bh, segment_mde_abs, small_sample
FROM sim.segment_results
