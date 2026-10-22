-- description: Foreign keys resolve to their parent tables (no orphans, no rows lost by inner joins).
-- severity: error
SELECT 'fct_orders.customer_id -> dim_customer' AS relationship, o.order_id AS key
FROM olist.fct_orders AS o
LEFT JOIN olist.dim_customer AS c ON o.customer_id = c.customer_id
WHERE c.customer_id IS NULL
UNION ALL
SELECT 'stg items.order_id -> orders', i.order_id
FROM stg.olist_order_items AS i
LEFT JOIN stg.olist_orders AS o ON i.order_id = o.order_id
WHERE o.order_id IS NULL
UNION ALL
SELECT 'stg payments.order_id -> orders', p.order_id
FROM stg.olist_order_payments AS p
LEFT JOIN stg.olist_orders AS o ON p.order_id = o.order_id
WHERE o.order_id IS NULL
UNION ALL
SELECT 'stg reviews.order_id -> orders', r.order_id
FROM stg.olist_order_reviews AS r
LEFT JOIN stg.olist_orders AS o ON r.order_id = o.order_id
WHERE o.order_id IS NULL
UNION ALL
SELECT 'fct_order_items.product_id -> dim_product', i.product_id
FROM olist.fct_order_items AS i
LEFT JOIN olist.dim_product AS p ON i.product_id = p.product_id
WHERE p.product_id IS NULL
UNION ALL
SELECT 'fct_order_items.seller_id -> dim_seller', i.seller_id
FROM olist.fct_order_items AS i
LEFT JOIN olist.dim_seller AS s ON i.seller_id = s.seller_id
WHERE s.seller_id IS NULL
UNION ALL
SELECT 'fct_orders.purchase_date -> dim_date', CAST(o.purchase_date AS VARCHAR)
FROM olist.fct_orders AS o
LEFT JOIN olist.dim_date AS d ON o.purchase_date = d.date
WHERE d.date IS NULL
UNION ALL
SELECT 'dim_customer.customer_state -> dim_geography', c.customer_state
FROM olist.dim_customer AS c
LEFT JOIN olist.dim_geography AS g ON c.customer_state = g.state_code
WHERE g.state_code IS NULL;
