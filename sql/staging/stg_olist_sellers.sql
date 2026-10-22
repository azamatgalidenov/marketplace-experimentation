-- Staging: one row per seller_id.
CREATE OR REPLACE VIEW stg.olist_sellers AS
SELECT
    seller_id,
    seller_zip_code_prefix,
    lower(trim(seller_city))  AS seller_city,
    upper(trim(seller_state)) AS seller_state
FROM raw.olist_sellers;
