-- Monthly delivery performance (measurable deliveries, analysis window, by purchase month).
SELECT
    purchase_month,
    count(*)                              AS measurable_orders,
    count(*) FILTER (WHERE is_late)       AS late_orders,
    avg(CAST(is_late AS DOUBLE))          AS late_rate,
    median(delivery_days)                 AS median_delivery_days,
    avg(estimated_delivery_days)          AS mean_promised_days
FROM olist.fct_orders
WHERE is_delivery_measurable AND in_analysis_window
GROUP BY purchase_month
ORDER BY purchase_month;
