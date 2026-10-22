-- description: At least 99% of orders with items and payments have payments equal to items + freight (within 0.01). Small gaps (e.g. instalment interest) are expected.
-- severity: warn
WITH comparable AS (
    SELECT abs(payment_value - order_gross_value) <= 0.01 AS matches
    FROM olist.fct_orders
    WHERE has_items AND payment_records > 0
)
SELECT
    count(*) AS orders_compared,
    avg(CASE WHEN matches THEN 1.0 ELSE 0.0 END) AS match_rate
FROM comparable
HAVING avg(CASE WHEN matches THEN 1.0 ELSE 0.0 END) < 0.99;
