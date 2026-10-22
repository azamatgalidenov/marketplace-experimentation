-- Dimension: calendar (grain: date), spanning every purchase date.
CREATE OR REPLACE TABLE olist.dim_date AS
WITH bounds AS (
    SELECT
        date_trunc('month', min(purchase_date))::DATE AS start_date,
        (date_trunc('month', max(purchase_date)) + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE
            AS end_date
    FROM olist.fct_orders
)
SELECT
    CAST(d.date AS DATE)                       AS date,
    year(d.date)                               AS year,
    quarter(d.date)                            AS quarter,
    month(d.date)                              AS month,
    strftime(d.date, '%Y-%m')                  AS year_month,
    date_trunc('month', d.date)::DATE          AS month_start,
    isodow(d.date)                             AS iso_day_of_week,
    strftime(d.date, '%a')                     AS day_name,
    (CAST(d.date AS DATE)
        BETWEEN getvariable('analysis_start') AND getvariable('analysis_end'))
                                               AS in_analysis_window
FROM bounds,
    generate_series(bounds.start_date, bounds.end_date, INTERVAL 1 DAY) AS d(date);
