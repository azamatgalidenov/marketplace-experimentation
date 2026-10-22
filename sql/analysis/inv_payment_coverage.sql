-- Investigation: orders whose payments and items do not overlap (excluded from the
-- payment-vs-items comparison), by status.
SELECT
    CASE
        WHEN has_items AND payment_records > 0 THEN 'items and payments'
        WHEN payment_records > 0               THEN 'payments, no items'
        WHEN has_items                         THEN 'items, no payments'
        ELSE                                        'neither'
    END                         AS coverage,
    order_status,
    count(*)                    AS orders,
    sum(payment_value)          AS payment_value
FROM olist.fct_orders
GROUP BY ALL
ORDER BY coverage, orders DESC;
