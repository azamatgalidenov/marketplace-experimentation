-- Fact: order lines (grain: order_id + order_item_id).
-- Carries order context (date, status, customer location) so category and seller
-- analyses do not need a fact-to-fact join back to fct_orders.
CREATE OR REPLACE TABLE olist.fct_order_items AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    p.category_name,
    o.order_status,
    o.purchase_date,
    o.in_analysis_window,
    o.customer_state,
    o.customer_region,
    s.seller_state,
    s.seller_region,
    i.item_price,
    i.freight_value,
    i.item_price + i.freight_value AS line_gross_value
FROM stg.olist_order_items AS i
INNER JOIN olist.fct_orders AS o  ON i.order_id = o.order_id
LEFT JOIN olist.dim_product AS p  ON i.product_id = p.product_id
LEFT JOIN olist.dim_seller AS s   ON i.seller_id = s.seller_id;
