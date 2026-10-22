-- description: Primary and foreign keys of the Olist marts are never NULL.
-- severity: error
SELECT 'fct_orders' AS model, order_id
FROM olist.fct_orders
WHERE order_id IS NULL OR customer_id IS NULL OR purchased_at IS NULL OR order_status IS NULL
UNION ALL
SELECT 'fct_order_items', order_id
FROM olist.fct_order_items
WHERE order_id IS NULL OR order_item_id IS NULL OR product_id IS NULL OR seller_id IS NULL
UNION ALL
SELECT 'fct_order_payments', order_id
FROM olist.fct_order_payments
WHERE order_id IS NULL OR payment_sequential IS NULL OR payment_type IS NULL;
