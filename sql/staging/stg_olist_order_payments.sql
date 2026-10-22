-- Staging: one row per payment instalment record (grain: order_id + payment_sequential).
-- An order can be paid with several methods (for example a voucher plus a credit card).
CREATE OR REPLACE VIEW stg.olist_order_payments AS
SELECT
    order_id,
    CAST(payment_sequential AS INTEGER)     AS payment_sequential,
    lower(trim(payment_type))               AS payment_type,
    CAST(payment_installments AS INTEGER)   AS payment_installments,
    CAST(payment_value AS DECIMAL(12, 2))   AS payment_value
FROM raw.olist_order_payments;
