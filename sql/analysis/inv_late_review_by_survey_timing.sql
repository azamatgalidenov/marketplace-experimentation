-- Investigation: low-review counts by lateness and by whether the satisfaction survey was
-- sent before the order reached the customer (measurable, reviewed, analysis window).
SELECT
    is_late,
    survey_sent_before_delivery,
    count(*)                                  AS reviewed_orders,
    count(*) FILTER (WHERE is_low_review)     AS low_reviews,
    avg(review_score)                         AS mean_score
FROM olist.fct_orders
WHERE is_delivery_measurable AND in_analysis_window AND review_score IS NOT NULL
GROUP BY is_late, survey_sent_before_delivery
ORDER BY is_late, survey_sent_before_delivery;
