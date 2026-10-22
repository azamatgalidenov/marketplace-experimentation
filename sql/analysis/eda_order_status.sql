-- Order status distribution (analysis window; denominator = all orders in window).
SELECT
    order_status,
    count(*)                              AS orders,
    count(*) / sum(count(*)) OVER ()      AS share,
    count(*) FILTER (WHERE has_items)     AS orders_with_items,
    sum(payment_value)                    AS payment_value
FROM olist.fct_orders
WHERE in_analysis_window
GROUP BY order_status
ORDER BY orders DESC;
