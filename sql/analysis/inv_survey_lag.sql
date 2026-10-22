-- Investigation: survey-sent date relative to the delivery date and to the promised date,
-- in days (measurable, reviewed deliveries).
SELECT
    date_diff('day', CAST(delivered_to_customer_at AS DATE), review_survey_sent_date)
                                                          AS days_from_delivery,
    count(*)                                              AS reviewed_orders,
    count(*) FILTER (WHERE is_late)                       AS late_orders,
    count(*) FILTER (WHERE review_survey_sent_date >= estimated_delivery_date)
                                                          AS sent_on_or_after_promised_date
FROM olist.fct_orders
WHERE is_delivery_measurable AND review_score IS NOT NULL
GROUP BY days_from_delivery
ORDER BY days_from_delivery;
