-- Power BI export: calendar. Grain: date.
SELECT date, year, quarter, month, year_month, month_start, in_analysis_window
FROM olist.dim_date
