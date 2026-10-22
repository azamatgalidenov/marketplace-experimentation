-- Staging: one row per product_id, with the English category name attached.
-- Categories without a translation keep their Portuguese name; products without a category
-- are labelled 'unknown'. Source column names misspell "length" as "lenght"; fixed here.
CREATE OR REPLACE VIEW stg.olist_products AS
SELECT
    p.product_id,
    p.product_category_name                                       AS category_name_pt,
    coalesce(t.product_category_name_english, p.product_category_name, 'unknown')
                                                                  AS category_name,
    CAST(p.product_name_lenght AS INTEGER)                        AS product_name_length,
    CAST(p.product_description_lenght AS INTEGER)                 AS product_description_length,
    CAST(p.product_photos_qty AS INTEGER)                         AS product_photos_qty,
    CAST(p.product_weight_g AS INTEGER)                           AS product_weight_g,
    CAST(p.product_length_cm AS INTEGER)                          AS product_length_cm,
    CAST(p.product_height_cm AS INTEGER)                          AS product_height_cm,
    CAST(p.product_width_cm AS INTEGER)                           AS product_width_cm
FROM raw.olist_products AS p
LEFT JOIN raw.olist_category_translation AS t
    ON p.product_category_name = t.product_category_name;
