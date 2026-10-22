-- Customer-region comparison (measurable deliveries, analysis window).
SELECT
    customer_region,
    count(*)                                            AS orders,
    avg(order_gross_value)                              AS aov_gross,
    avg(freight_value / nullif(order_gross_value, 0))   AS mean_freight_share,
    median(delivery_days)                               AS median_delivery_days,
    avg(estimated_delivery_days)                        AS mean_promised_days,
    count(*) FILTER (WHERE is_late)                     AS late_orders,
    avg(CAST(is_late AS DOUBLE))                        AS late_rate,
    count(review_score)                                 AS reviewed_orders,
    count(*) FILTER (WHERE is_low_review)               AS low_reviews,
    avg(CAST(is_low_review AS DOUBLE))                  AS low_review_rate
FROM olist.fct_orders
WHERE is_delivery_measurable AND in_analysis_window
GROUP BY customer_region
ORDER BY orders DESC;
