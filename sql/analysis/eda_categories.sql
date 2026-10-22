-- Category comparison (analysis window).
-- Value metrics are item level from fct_order_items (delivered orders; each line once).
-- Experience metrics are order level by the order's primary category (measurable
-- deliveries; each order once), so multi-category orders are never double counted.
WITH item_level AS (
    SELECT
        category_name,
        count(DISTINCT order_id)                    AS orders_containing,
        count(*)                                    AS items,
        sum(item_price)                             AS gmv,
        avg(item_price)                             AS mean_item_price,
        sum(freight_value) / sum(line_gross_value)  AS freight_share
    FROM olist.fct_order_items
    WHERE order_status = 'delivered' AND in_analysis_window
    GROUP BY category_name
),

order_level AS (
    SELECT
        primary_category                         AS category_name,
        count(*)                                 AS primary_orders,
        count(*) FILTER (WHERE is_late)          AS late_orders,
        avg(CAST(is_late AS DOUBLE))             AS late_rate,
        count(review_score)                      AS reviewed_orders,
        count(*) FILTER (WHERE is_low_review)    AS low_reviews,
        avg(CAST(is_low_review AS DOUBLE))       AS low_review_rate
    FROM olist.fct_orders
    WHERE is_delivery_measurable AND in_analysis_window
    GROUP BY primary_category
)

SELECT
    i.*,
    o.primary_orders,
    o.late_orders,
    o.late_rate,
    o.reviewed_orders,
    o.low_reviews,
    o.low_review_rate
FROM item_level AS i
LEFT JOIN order_level AS o USING (category_name)
ORDER BY i.gmv DESC;
