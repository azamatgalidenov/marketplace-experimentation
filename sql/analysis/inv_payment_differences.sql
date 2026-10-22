-- Investigation: payment value vs items + freight, in exact integer cents (DECIMAL
-- arithmetic, no floating point). Orders with both items and payments.
WITH diffs AS (
    SELECT
        *,
        CAST((payment_value - order_gross_value) * 100 AS BIGINT) AS diff_cents
    FROM olist.fct_orders
    WHERE has_items AND payment_records > 0
)
SELECT
    CASE
        WHEN diff_cents = 0      THEN '1: exact match'
        WHEN abs(diff_cents) = 1 THEN '2: 1 cent apart'
        WHEN diff_cents > 1      THEN '3: paid more than items + freight'
        ELSE                          '4: paid less than items + freight'
    END                                                    AS difference_class,
    count(*)                                               AS orders,
    sum(diff_cents) / 100.0                                AS net_difference,
    median(diff_cents) / 100.0                             AS median_difference,
    avg(CAST(max_installments > 1 AS DOUBLE))              AS share_installments_gt_1,
    avg(CAST(primary_payment_type = 'credit_card' AS DOUBLE)) AS share_credit_card,
    avg(CAST(payment_records > 1 AS DOUBLE))               AS share_multiple_payments,
    avg(CAST(used_voucher AS DOUBLE))                      AS share_voucher,
    avg(CAST(order_status <> 'delivered' AS DOUBLE))       AS share_not_delivered,
    avg(CAST(item_count > 1 AS DOUBLE))                    AS share_multi_item
FROM diffs
GROUP BY difference_class
ORDER BY difference_class;
