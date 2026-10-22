-- Candidate rows for the low-review model: one row per order in the analysis window
-- (grain: order_id, from fct_orders). Eligibility filters are applied step by step in
-- Python (statistics/low_review_model.py) so every exclusion is counted and reported.
--
-- Only pre-review information is selected as a predictor. Fields that are produced by
-- the review itself (comment flag, review count) are not used.
SELECT
    order_id,
    customer_unique_id,
    primary_seller_id,
    order_status,
    is_delivery_measurable,
    purchased_at,
    purchase_date,
    strftime(purchase_month, '%Y-%m')               AS purchase_month,
    delivered_to_customer_at,
    estimated_delivery_date,
    estimated_delivery_days,
    delivery_delay_days,
    review_score,
    review_count,
    review_survey_sent_date,
    review_answered_at,
    items_value,
    freight_value,
    order_gross_value,
    item_count,
    distinct_sellers,
    primary_category,
    customer_region
FROM olist.fct_orders
WHERE in_analysis_window
ORDER BY order_id;
