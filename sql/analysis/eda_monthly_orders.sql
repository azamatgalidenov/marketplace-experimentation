-- Monthly order volume and value (analysis window only).
-- orders: all statuses; gross value and AOV: delivered orders only.
SELECT
    purchase_month,
    count(*)                                                          AS orders,
    count(*) FILTER (WHERE order_status = 'delivered')                AS delivered_orders,
    sum(order_gross_value) FILTER (WHERE order_status = 'delivered')  AS delivered_gross_value,
    avg(order_gross_value) FILTER (WHERE order_status = 'delivered')  AS delivered_aov
FROM olist.fct_orders
WHERE in_analysis_window
GROUP BY purchase_month
ORDER BY purchase_month;
