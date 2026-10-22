-- Investigation: how the late-delivery population is formed and how sensitive the rate is
-- to the definition. One row per population step / definition.
WITH base AS (SELECT * FROM olist.fct_orders)
SELECT 1 AS step, 'All orders' AS population, count(*) AS orders,
       NULL::DOUBLE AS late_rate_date_level, NULL::DOUBLE AS late_rate_timestamp_level
FROM base
UNION ALL
SELECT 2, 'Status delivered', count(*), NULL, NULL
FROM base WHERE order_status = 'delivered'
UNION ALL
SELECT 3, 'Delivered with customer-delivery timestamp (measurable)', count(*),
       avg(CAST(is_late AS DOUBLE)),
       avg(CAST(delivered_to_customer_at > CAST(estimated_delivery_date AS TIMESTAMP) AS DOUBLE))
FROM base WHERE is_delivery_measurable
UNION ALL
SELECT 4, 'Measurable, in analysis window (headline)', count(*),
       avg(CAST(is_late AS DOUBLE)),
       avg(CAST(delivered_to_customer_at > CAST(estimated_delivery_date AS TIMESTAMP) AS DOUBLE))
FROM base WHERE is_delivery_measurable AND in_analysis_window
UNION ALL
SELECT 5, 'Not delivered but has delivery timestamp (excluded)', count(*),
       avg(CAST(is_late AS DOUBLE)), NULL
FROM base WHERE order_status <> 'delivered' AND delivered_to_customer_at IS NOT NULL
UNION ALL
SELECT 6, 'Delivered without delivery timestamp (excluded)', count(*), NULL, NULL
FROM base WHERE order_status = 'delivered' AND delivered_to_customer_at IS NULL
ORDER BY step;
