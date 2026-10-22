-- Dimension: products (grain: product_id).
CREATE OR REPLACE TABLE olist.dim_product AS
SELECT
    product_id,
    category_name,
    category_name_pt,
    product_photos_qty,
    product_weight_g,
    product_length_cm * product_height_cm * product_width_cm AS product_volume_cm3
FROM stg.olist_products;
