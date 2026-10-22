-- Investigation: low-review rate by order status (all orders with a review). Orders that
-- never reached the customer provide context for pre-delivery reviews.
SELECT
    order_status,
    count(*)                                AS reviewed_orders,
    count(*) FILTER (WHERE is_low_review)   AS low_reviews,
    avg(review_score)                       AS mean_score
FROM olist.fct_orders
WHERE review_score IS NOT NULL
GROUP BY order_status
ORDER BY reviewed_orders DESC;
