-- Distribution of delivery delay in days (delivery date minus promised date) for
-- measurable deliveries in the analysis window. Negative = early.
SELECT
    delivery_delay_days,
    count(*) AS orders
FROM olist.fct_orders
WHERE is_delivery_measurable AND in_analysis_window
GROUP BY delivery_delay_days
ORDER BY delivery_delay_days;
