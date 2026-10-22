-- Power BI export: historical order fact (real Olist data). Grain: order_id.
-- Adds report helper columns: delay bucket (+ sort key) and survey timing class.
SELECT
    order_id,
    customer_unique_id,
    customer_state,
    customer_region,
    order_status,
    purchase_date,
    primary_category,
    item_count,
    items_value,
    freight_value,
    order_gross_value,
    payment_value,
    primary_payment_type,
    is_delivery_measurable,
    delivery_days,
    delivery_delay_days,
    is_late,
    review_score,
    is_low_review,
    CASE
        WHEN NOT is_delivery_measurable THEN 'Not measurable'
        WHEN delivery_delay_days <= -15 THEN '15+ days early'
        WHEN delivery_delay_days <= -8  THEN '8-14 days early'
        WHEN delivery_delay_days <= -1  THEN '1-7 days early'
        WHEN delivery_delay_days = 0    THEN 'On promised day'
        WHEN delivery_delay_days <= 3   THEN '1-3 days late'
        WHEN delivery_delay_days <= 7   THEN '4-7 days late'
        WHEN delivery_delay_days <= 14  THEN '8-14 days late'
        ELSE '15+ days late'
    END AS delay_bucket,
    CASE
        WHEN NOT is_delivery_measurable THEN 99
        WHEN delivery_delay_days <= -15 THEN 1
        WHEN delivery_delay_days <= -8  THEN 2
        WHEN delivery_delay_days <= -1  THEN 3
        WHEN delivery_delay_days = 0    THEN 4
        WHEN delivery_delay_days <= 3   THEN 5
        WHEN delivery_delay_days <= 7   THEN 6
        WHEN delivery_delay_days <= 14  THEN 7
        ELSE 8
    END AS delay_bucket_order,
    -- Survey timing (review_survey_sent_date = date the survey was sent, day precision).
    CASE
        WHEN review_score IS NULL OR delivered_to_customer_at IS NULL THEN 'n/a'
        WHEN review_survey_sent_date < CAST(delivered_to_customer_at AS DATE) THEN 'Sent before delivery'
        WHEN review_survey_sent_date = CAST(delivered_to_customer_at AS DATE) THEN 'Sent on delivery day'
        ELSE 'Sent after delivery'
    END AS survey_timing
FROM olist.fct_orders
