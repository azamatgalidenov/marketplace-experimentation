-- Power BI export: SIMULATED scenario dimension (the only link between simulated tables).
-- Grain: scenario. Carries the pre-registered decision and the sample-ratio-mismatch check.
SELECT
    d.scenario,
    d.description,
    d.decision,
    d.reasons AS decision_reasons,
    CASE d.scenario WHEN 'aa' THEN 1 WHEN 'null_effect' THEN 2 WHEN 'positive' THEN 3
         WHEN 'small_effect' THEN 4 WHEN 'guardrail_harm' THEN 5 ELSE 9 END AS scenario_order,
    s.chi2 AS srm_chi2,
    s.p_value AS srm_p_value,
    s.srm_detected
FROM sim.decisions AS d
JOIN sim.srm_checks AS s USING (scenario)
