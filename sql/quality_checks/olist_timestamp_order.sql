-- description: Orders are not delivered to the customer before they were purchased.
-- severity: error
SELECT order_id, purchased_at, delivered_to_customer_at
FROM olist.fct_orders
WHERE delivered_to_customer_at < purchased_at;
