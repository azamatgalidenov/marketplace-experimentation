-- description: Order-level totals and row counts reconcile exactly with line-level sources (no fan-out, no lost rows).
-- severity: error
WITH checks AS (
    SELECT 'items_value: fct_orders vs stg items' AS rule,
        (SELECT sum(items_value) FROM olist.fct_orders) AS mart_value,
        (SELECT sum(item_price) FROM stg.olist_order_items) AS source_value
    UNION ALL
    SELECT 'freight_value: fct_orders vs stg items',
        (SELECT sum(freight_value) FROM olist.fct_orders),
        (SELECT sum(freight_value) FROM stg.olist_order_items)
    UNION ALL
    SELECT 'payment_value: fct_orders vs stg payments',
        (SELECT sum(payment_value) FROM olist.fct_orders),
        (SELECT sum(payment_value) FROM stg.olist_order_payments)
    UNION ALL
    SELECT 'item_count: fct_orders vs fct_order_items rows',
        (SELECT sum(item_count) FROM olist.fct_orders),
        (SELECT count(*) FROM olist.fct_order_items)
    UNION ALL
    SELECT 'rows: fct_orders vs stg orders',
        (SELECT count(*) FROM olist.fct_orders),
        (SELECT count(*) FROM stg.olist_orders)
    UNION ALL
    SELECT 'rows: fct_order_items vs stg items',
        (SELECT count(*) FROM olist.fct_order_items),
        (SELECT count(*) FROM stg.olist_order_items)
    UNION ALL
    SELECT 'rows: fct_order_payments vs stg payments',
        (SELECT count(*) FROM olist.fct_order_payments),
        (SELECT count(*) FROM stg.olist_order_payments)
    UNION ALL
    SELECT 'rows: dim_customer vs fct_orders',
        (SELECT count(*) FROM olist.dim_customer),
        (SELECT count(*) FROM olist.fct_orders)
)
SELECT * FROM checks WHERE coalesce(mart_value, 0) <> coalesce(source_value, 0);
