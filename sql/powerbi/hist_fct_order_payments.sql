-- Power BI export: historical payment records (real Olist data). Grain: order_id + payment_sequential.
-- Customer region is added from fct_orders (one row per order, no fan-out) so the region
-- slicer filters payments too.
SELECT p.order_id, p.payment_sequential, p.payment_type, p.payment_installments,
       p.payment_value, p.order_status, p.purchase_date, o.customer_region
FROM olist.fct_order_payments AS p
JOIN olist.fct_orders AS o USING (order_id)
