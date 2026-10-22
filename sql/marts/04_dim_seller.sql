-- Dimension: sellers (grain: seller_id).
CREATE OR REPLACE TABLE olist.dim_seller AS
SELECT
    s.seller_id,
    s.seller_zip_code_prefix,
    s.seller_city,
    s.seller_state,
    g.region AS seller_region
FROM stg.olist_sellers AS s
LEFT JOIN olist.dim_geography AS g
    ON s.seller_state = g.state_code;
