-- Staging: one row per (review_id, order_id).
-- review_id alone is not unique in the source: the same review id can be attached to
-- several orders, and some orders have several reviews. Free-text columns are dropped;
-- only a flag recording whether a comment was written is kept.
CREATE OR REPLACE VIEW stg.olist_order_reviews AS
SELECT
    review_id,
    order_id,
    CAST(review_score AS INTEGER)                           AS review_score,
    (nullif(trim(review_comment_message), '') IS NOT NULL)  AS has_comment,
    CAST(review_creation_date AS TIMESTAMP)                 AS review_created_at,
    CAST(review_answer_timestamp AS TIMESTAMP)              AS review_answered_at
FROM raw.olist_order_reviews;
