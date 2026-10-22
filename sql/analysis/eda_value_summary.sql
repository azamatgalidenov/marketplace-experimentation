-- Headline value metrics (analysis window). Gross customer payments, not platform revenue.
SELECT
    count(*)                                                            AS orders,
    count(*) FILTER (WHERE order_status = 'delivered')                  AS delivered_orders,
    sum(items_value) FILTER (WHERE order_status = 'delivered')          AS delivered_gmv,
    sum(freight_value) FILTER (WHERE order_status = 'delivered')        AS delivered_freight,
    sum(order_gross_value) FILTER (WHERE order_status = 'delivered')    AS delivered_gross_value,
    sum(payment_value)                                                  AS payment_value_all_statuses,
    sum(payment_value) FILTER (WHERE NOT has_items)                     AS payment_value_orders_without_items,
    avg(order_gross_value) FILTER (WHERE order_status = 'delivered')    AS aov_gross_delivered,
    median(order_gross_value) FILTER (WHERE order_status = 'delivered') AS median_gross_delivered,
    quantile_cont(order_gross_value, 0.9) FILTER (WHERE order_status = 'delivered')
                                                                        AS p90_gross_delivered,
    avg(freight_value / nullif(order_gross_value, 0)) FILTER (WHERE order_status = 'delivered')
                                                                        AS mean_freight_share
FROM olist.fct_orders
WHERE in_analysis_window;
