-- Staging: one row per order (grain: order_id).
-- Casts types and normalises the status. No business logic, no joins.
CREATE OR REPLACE VIEW stg.olist_orders AS
SELECT
    order_id,
    customer_id,
    lower(trim(order_status))                       AS order_status,
    CAST(order_purchase_timestamp AS TIMESTAMP)      AS purchased_at,
    CAST(order_approved_at AS TIMESTAMP)             AS approved_at,
    CAST(order_delivered_carrier_date AS TIMESTAMP)  AS delivered_to_carrier_at,
    CAST(order_delivered_customer_date AS TIMESTAMP) AS delivered_to_customer_at,
    -- The estimate is published as a date (time is always 00:00:00).
    CAST(CAST(order_estimated_delivery_date AS TIMESTAMP) AS DATE) AS estimated_delivery_date
FROM raw.olist_orders;
