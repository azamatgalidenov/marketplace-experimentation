-- Power BI export: product categories present in orders or order lines. Grain: category_name.
SELECT category_name FROM olist.fct_order_items WHERE category_name IS NOT NULL
UNION
SELECT primary_category FROM olist.fct_orders WHERE primary_category IS NOT NULL
