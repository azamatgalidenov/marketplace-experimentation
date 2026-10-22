-- Review-score distribution (latest review per order, analysis window, all statuses).
-- Orders without a review are listed but excluded from the share denominator.
SELECT
    review_score,
    count(*)                                                    AS orders,
    CASE WHEN review_score IS NOT NULL
        THEN count(*) / sum(count(*) FILTER (WHERE review_score IS NOT NULL)) OVER ()
    END                                                         AS share_of_reviewed
FROM olist.fct_orders
WHERE in_analysis_window
GROUP BY review_score
ORDER BY review_score NULLS LAST;
