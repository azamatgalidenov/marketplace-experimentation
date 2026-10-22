-- Payment-method mix at payment-record level (analysis window, all statuses).
-- orders_using_method counts distinct orders; an order can use several methods, so these
-- counts do not add up to the number of orders.
SELECT
    payment_type,
    count(*)                                              AS payment_records,
    count(DISTINCT order_id)                              AS orders_using_method,
    sum(payment_value)                                    AS payment_value,
    sum(payment_value) / sum(sum(payment_value)) OVER ()  AS value_share,
    avg(payment_installments)                             AS mean_installments
FROM olist.fct_order_payments
WHERE in_analysis_window
GROUP BY payment_type
ORDER BY payment_value DESC;
