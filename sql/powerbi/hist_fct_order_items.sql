-- Power BI export: historical order lines (real Olist data). Grain: order_id + order_item_id.
SELECT order_id, order_item_id, product_id, seller_id, category_name, order_status,
       purchase_date, customer_state, customer_region, item_price, freight_value, line_gross_value
FROM olist.fct_order_items
