-- Fact: orders (grain: order_id). The central analytical table.
--
-- Fan-out prevention: items, payments and reviews are each aggregated to one row per
-- order in their own CTE before being joined to orders, so no join can duplicate
-- order-level values.
--
-- Value definitions (gross values paid by customers, not Olist platform revenue):
--   items_value       = sum of item prices (merchandise value)
--   freight_value     = sum of freight charged
--   order_gross_value = items_value + freight_value
--   payment_value     = sum of recorded payments (can differ slightly from
--                       order_gross_value, e.g. instalment interest or vouchers)
CREATE OR REPLACE TABLE olist.fct_orders AS
WITH items AS (
    SELECT
        order_id,
        count(*)                      AS item_count,
        count(DISTINCT product_id)    AS distinct_products,
        count(DISTINCT seller_id)     AS distinct_sellers,
        sum(item_price)               AS items_value,
        sum(freight_value)            AS freight_value
    FROM stg.olist_order_items
    GROUP BY order_id
),

-- Category of the most expensive line (ties: lowest line number).
primary_item AS (
    SELECT
        i.order_id,
        p.category_name AS primary_category,
        i.seller_id     AS primary_seller_id
    FROM stg.olist_order_items AS i
    LEFT JOIN stg.olist_products AS p
        ON i.product_id = p.product_id
    QUALIFY row_number() OVER (
        PARTITION BY i.order_id ORDER BY i.item_price DESC, i.order_item_id
    ) = 1
),

payment_by_type AS (
    SELECT order_id, payment_type, sum(payment_value) AS type_value
    FROM stg.olist_order_payments
    GROUP BY order_id, payment_type
),

payments AS (
    SELECT
        order_id,
        count(*)                                        AS payment_records,
        sum(payment_value)                              AS payment_value,
        max(payment_installments)                       AS max_installments,
        bool_or(payment_type = 'voucher')               AS used_voucher
    FROM stg.olist_order_payments
    GROUP BY order_id
),

-- Payment type that covered the largest share of the order value.
primary_payment AS (
    SELECT order_id, payment_type AS primary_payment_type
    FROM payment_by_type
    QUALIFY row_number() OVER (
        PARTITION BY order_id ORDER BY type_value DESC, payment_type
    ) = 1
),

-- Some orders have several reviews; keep the most recently answered one.
reviews AS (
    SELECT
        order_id,
        review_score,
        has_comment       AS review_has_comment,
        review_created_at,
        review_answered_at,
        count(*) OVER (PARTITION BY order_id) AS review_count
    FROM stg.olist_order_reviews
    QUALIFY row_number() OVER (
        PARTITION BY order_id
        ORDER BY review_answered_at DESC, review_created_at DESC, review_id
    ) = 1
)

SELECT
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_state,
    c.customer_region,
    c.is_repeat_purchase,
    o.order_status,
    o.purchased_at,
    CAST(o.purchased_at AS DATE)                              AS purchase_date,
    date_trunc('month', o.purchased_at)::DATE                 AS purchase_month,
    (CAST(o.purchased_at AS DATE)
        BETWEEN getvariable('analysis_start') AND getvariable('analysis_end'))
                                                              AS in_analysis_window,
    o.approved_at,
    o.delivered_to_carrier_at,
    o.delivered_to_customer_at,
    o.estimated_delivery_date,

    -- Items and value
    coalesce(i.item_count, 0)                                 AS item_count,
    coalesce(i.distinct_products, 0)                          AS distinct_products,
    coalesce(i.distinct_sellers, 0)                           AS distinct_sellers,
    (i.order_id IS NOT NULL)                                  AS has_items,
    pi.primary_category,
    pi.primary_seller_id,
    coalesce(i.items_value, 0)                                AS items_value,
    coalesce(i.freight_value, 0)                              AS freight_value,
    coalesce(i.items_value, 0) + coalesce(i.freight_value, 0) AS order_gross_value,

    -- Payments
    coalesce(p.payment_value, 0)                              AS payment_value,
    coalesce(p.payment_records, 0)                            AS payment_records,
    pp.primary_payment_type,
    p.max_installments,
    coalesce(p.used_voucher, FALSE)                           AS used_voucher,

    -- Delivery (measurable only when the order reached the customer)
    (o.order_status = 'delivered' AND o.delivered_to_customer_at IS NOT NULL)
                                                              AS is_delivery_measurable,
    CASE WHEN o.delivered_to_customer_at IS NOT NULL
        THEN date_diff('second', o.purchased_at, o.delivered_to_customer_at) / 86400.0
    END                                                       AS delivery_days,
    date_diff('day', CAST(o.purchased_at AS DATE), o.estimated_delivery_date)
                                                              AS estimated_delivery_days,
    -- Positive = days after the promised date; negative = early.
    CASE WHEN o.delivered_to_customer_at IS NOT NULL
        THEN date_diff('day', o.estimated_delivery_date, CAST(o.delivered_to_customer_at AS DATE))
    END                                                       AS delivery_delay_days,
    CASE WHEN o.delivered_to_customer_at IS NOT NULL
        THEN CAST(o.delivered_to_customer_at AS DATE) > o.estimated_delivery_date
    END                                                       AS is_late,

    -- Reviews
    r.review_score,
    coalesce(r.review_count, 0)                               AS review_count,
    r.review_has_comment,
    CASE WHEN r.review_score IS NOT NULL
        THEN r.review_score <= getvariable('low_review_max_score')
    END                                                       AS is_low_review,
    -- Source semantics (Olist data description): review_creation_date is the date the
    -- satisfaction survey was sent (date-only, always 00:00); review_answer_timestamp is
    -- when the customer answered it. Both are kept so timing questions can use the right one.
    CAST(r.review_created_at AS DATE)                         AS review_survey_sent_date,
    r.review_answered_at,
    CASE WHEN r.review_score IS NOT NULL AND o.delivered_to_customer_at IS NOT NULL
        THEN CAST(r.review_created_at AS DATE) < CAST(o.delivered_to_customer_at AS DATE)
    END                                                       AS survey_sent_before_delivery,
    CASE WHEN r.review_score IS NOT NULL AND o.delivered_to_customer_at IS NOT NULL
        THEN r.review_answered_at < o.delivered_to_customer_at
    END                                                       AS answered_before_delivery
FROM stg.olist_orders AS o
LEFT JOIN olist.dim_customer AS c   ON o.customer_id = c.customer_id
LEFT JOIN items AS i                ON o.order_id = i.order_id
LEFT JOIN primary_item AS pi        ON o.order_id = pi.order_id
LEFT JOIN payments AS p             ON o.order_id = p.order_id
LEFT JOIN primary_payment AS pp     ON o.order_id = pp.order_id
LEFT JOIN reviews AS r              ON o.order_id = r.order_id;
