-- Low-review rate by delivery-delay bucket (measurable, reviewed, analysis window).
-- Observational: lateness is not randomly assigned.
SELECT
    CASE
        WHEN delivery_delay_days <= -15 THEN '15+ days early'
        WHEN delivery_delay_days <= -8  THEN '8-14 days early'
        WHEN delivery_delay_days <= -1  THEN '1-7 days early'
        WHEN delivery_delay_days = 0    THEN 'On promised day'
        WHEN delivery_delay_days <= 3   THEN '1-3 days late'
        WHEN delivery_delay_days <= 7   THEN '4-7 days late'
        WHEN delivery_delay_days <= 14  THEN '8-14 days late'
        ELSE                                 '15+ days late'
    END                                      AS delay_bucket,
    min(delivery_delay_days)                 AS bucket_order,
    count(*)                                 AS reviewed_orders,
    count(*) FILTER (WHERE is_low_review)    AS low_reviews,
    avg(review_score)                        AS mean_score
FROM olist.fct_orders
WHERE is_delivery_measurable AND in_analysis_window AND review_score IS NOT NULL
GROUP BY delay_bucket
ORDER BY bucket_order;
