-- Staging: one row per customer_id.
-- customer_id is created per order (1:1 with orders); customer_unique_id identifies the person.
CREATE OR REPLACE VIEW stg.olist_customers AS
SELECT
    customer_id,
    customer_unique_id,
    customer_zip_code_prefix,
    lower(trim(customer_city))  AS customer_city,
    upper(trim(customer_state)) AS customer_state
FROM raw.olist_customers;
