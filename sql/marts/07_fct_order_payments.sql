-- Fact: payment records (grain: order_id + payment_sequential).
CREATE OR REPLACE TABLE olist.fct_order_payments AS
SELECT
    p.order_id,
    p.payment_sequential,
    p.payment_type,
    p.payment_installments,
    p.payment_value,
    o.order_status,
    o.purchase_date,
    o.in_analysis_window
FROM stg.olist_order_payments AS p
INNER JOIN olist.fct_orders AS o ON p.order_id = o.order_id;
