-- Dimension: customers (grain: customer_id, i.e. one row per order's customer record).
-- customer_unique_id identifies the person across orders. customer_order_number ranks a
-- person's orders by purchase time, so repeat purchasing can be measured.
CREATE OR REPLACE TABLE olist.dim_customer AS
WITH person_orders AS (
    SELECT
        c.customer_id,
        row_number() OVER (
            PARTITION BY c.customer_unique_id
            ORDER BY o.purchased_at, o.order_id
        ) AS customer_order_number
    FROM stg.olist_customers AS c
    LEFT JOIN stg.olist_orders AS o
        ON c.customer_id = o.customer_id
)
SELECT
    c.customer_id,
    c.customer_unique_id,
    c.customer_zip_code_prefix,
    c.customer_city,
    c.customer_state,
    g.state_name AS customer_state_name,
    g.region     AS customer_region,
    p.customer_order_number,
    (p.customer_order_number > 1) AS is_repeat_purchase
FROM stg.olist_customers AS c
LEFT JOIN person_orders AS p
    ON c.customer_id = p.customer_id
LEFT JOIN olist.dim_geography AS g
    ON c.customer_state = g.state_code;
