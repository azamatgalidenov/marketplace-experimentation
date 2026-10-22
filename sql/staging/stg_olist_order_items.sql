-- Staging: one row per order line (grain: order_id + order_item_id).
-- Olist repeats a line for each unit purchased, so a quantity of 3 appears as 3 rows.
CREATE OR REPLACE VIEW stg.olist_order_items AS
SELECT
    order_id,
    CAST(order_item_id AS INTEGER)              AS order_item_id,
    product_id,
    seller_id,
    CAST(shipping_limit_date AS TIMESTAMP)      AS shipping_limit_at,
    CAST(price AS DECIMAL(12, 2))               AS item_price,
    CAST(freight_value AS DECIMAL(12, 2))       AS freight_value
FROM raw.olist_order_items;
