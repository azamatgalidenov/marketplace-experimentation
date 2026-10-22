-- description: Categorical fields contain only documented values.
-- severity: error
SELECT 'order_status' AS field, order_status AS value
FROM olist.fct_orders
WHERE order_status NOT IN (
    'created', 'approved', 'invoiced', 'processing', 'shipped', 'delivered',
    'canceled', 'unavailable'
)
UNION ALL
SELECT 'payment_type', payment_type
FROM olist.fct_order_payments
WHERE payment_type NOT IN ('credit_card', 'boleto', 'voucher', 'debit_card', 'not_defined')
UNION ALL
SELECT 'review_score', CAST(review_score AS VARCHAR)
FROM stg.olist_order_reviews
WHERE review_score NOT BETWEEN 1 AND 5 OR review_score IS NULL;
