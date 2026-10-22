-- description: Every Olist mart is unique at its documented grain.
-- severity: error
SELECT 'fct_orders' AS model, order_id AS key, count(*) AS n
FROM olist.fct_orders GROUP BY order_id HAVING count(*) > 1
UNION ALL
SELECT 'fct_order_items', order_id || '#' || order_item_id, count(*)
FROM olist.fct_order_items GROUP BY order_id, order_item_id HAVING count(*) > 1
UNION ALL
SELECT 'fct_order_payments', order_id || '#' || payment_sequential, count(*)
FROM olist.fct_order_payments GROUP BY order_id, payment_sequential HAVING count(*) > 1
UNION ALL
SELECT 'dim_customer', customer_id, count(*)
FROM olist.dim_customer GROUP BY customer_id HAVING count(*) > 1
UNION ALL
SELECT 'dim_product', product_id, count(*)
FROM olist.dim_product GROUP BY product_id HAVING count(*) > 1
UNION ALL
SELECT 'dim_seller', seller_id, count(*)
FROM olist.dim_seller GROUP BY seller_id HAVING count(*) > 1
UNION ALL
SELECT 'dim_date', CAST(date AS VARCHAR), count(*)
FROM olist.dim_date GROUP BY date HAVING count(*) > 1
UNION ALL
SELECT 'dim_geography', state_code, count(*)
FROM olist.dim_geography GROUP BY state_code HAVING count(*) > 1;
