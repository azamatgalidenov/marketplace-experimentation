-- Credit-card instalment distribution (payment records, analysis window).
-- A handful of records report 0 instalments; they are kept as reported.
SELECT
    payment_installments,
    count(*)                              AS payment_records,
    count(*) / sum(count(*)) OVER ()      AS share,
    avg(payment_value)                    AS mean_payment_value
FROM olist.fct_order_payments
WHERE in_analysis_window AND payment_type = 'credit_card'
GROUP BY payment_installments
ORDER BY payment_installments;
