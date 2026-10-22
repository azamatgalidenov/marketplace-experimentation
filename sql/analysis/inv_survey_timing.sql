-- Investigation: orders whose satisfaction survey was sent (review_creation_date) before
-- the customer-delivery date. All measurable, reviewed deliveries (no window filter).
SELECT
    survey_sent_before_delivery,
    is_late,
    review_survey_sent_date >= estimated_delivery_date   AS sent_on_or_after_promised_date,
    answered_before_delivery,
    count(*)                                              AS reviewed_orders,
    count(*) FILTER (WHERE is_low_review)                 AS low_reviews,
    avg(review_score)                                     AS mean_score
FROM olist.fct_orders
WHERE is_delivery_measurable AND review_score IS NOT NULL
GROUP BY ALL
ORDER BY ALL;
