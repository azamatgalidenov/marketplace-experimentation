-- description: Monetary amounts and counts are non-negative.
-- severity: error
SELECT 'item_price < 0' AS rule, order_id FROM olist.fct_order_items WHERE item_price < 0
UNION ALL
SELECT 'freight_value < 0', order_id FROM olist.fct_order_items WHERE freight_value < 0
UNION ALL
SELECT 'payment_value < 0', order_id FROM olist.fct_order_payments WHERE payment_value < 0
UNION ALL
SELECT 'payment_installments < 0', order_id
FROM olist.fct_order_payments WHERE payment_installments < 0;
