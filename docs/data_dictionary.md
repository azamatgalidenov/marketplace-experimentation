# Data dictionary: historical Olist model (`olist` schema)

All tables in the `olist` schema are built from **real Olist data**. Simulated
experiment tables live only in the `sim` schema and are documented in
`docs/methodology.md`.

Row counts below come from the Kaggle archive with SHA-256 `967e41e0…6deca784`,
downloaded on 2026-10-14.

## 1. Source tables and keys (as profiled)

| Source CSV | Rows | Primary key | Notes |
|---|---:|---|---|
| orders | 99,441 | `order_id` | 8 statuses; 96,478 `delivered` |
| order_items | 112,650 | `order_id, order_item_id` | One row per **unit**. 1,278 orders have more than one seller |
| order_payments | 103,886 | `order_id, payment_sequential` | An order can combine methods (e.g. voucher + card) |
| order_reviews | 99,224 | `review_id, order_id` | **`review_id` is not unique** (98,410 distinct). 547 orders have more than one review; 768 orders have none |
| customers | 99,441 | `customer_id` | `customer_id` is 1:1 with orders. `customer_unique_id` (96,096 people) identifies the person |
| products | 32,951 | `product_id` | 610 products have no category |
| sellers | 3,095 | `seller_id` | |
| category_translation | 71 | `product_category_name` | `pc_gamer` and `portateis_cozinha_e_preparadores_de_alimentos` have no translation |

### Relationships

```
customers 1 ── 1 orders 1 ── * order_items * ── 1 products
                    │                  └──── * ── 1 sellers
                    ├── * order_payments
                    └── * order_reviews  (review_id can repeat across orders)
```

All foreign keys resolve: there are no orphan items, payments or reviews, and the
`olist_relationships` check enforces this on every build.

### Data-quality observations

| Issue | Size | Handling |
|---|---:|---|
| Orders with no items | 775 (603 `unavailable`, 164 `canceled`, …) | Kept; `has_items = false`, values = 0 |
| Orders with no payment records | 1 | Kept; `payment_value = 0` |
| Orders with more than one review | 547 | The most recently answered review is used |
| Orders with no review | 768 | `review_score` is NULL; excluded from review metrics |
| `delivered` orders without a delivery timestamp | 8 | `is_delivery_measurable = false` |
| `canceled` orders with a delivery timestamp | 6 | Kept as reported; delivery metrics use `delivered` orders only |
| Payments ≠ items + freight (exact integer cents) | 576 of 98,665 orders: 273 differ by exactly 1 cent, 264 paid more, 39 paid less | Both values kept; never netted away by a tolerance. See `reports/eda_findings.md` §3.4. (Milestone 1 reported 387 using a floating-point comparison; that figure was wrong.) |
| Orders with payments but **no items** | 775 orders, R$162,591.95 | Kept; included in `payment_value` totals but not in GMV or AOV |
| Survey date before purchase date | 64 (63 also answered before purchase) | Kept; source inconsistency. Date-level comparison (a timestamp comparison overstates it as 74) |
| Handed to carrier before purchase timestamp | 166 (only 2 on an earlier calendar day) | Kept; carrier timestamps are not used in metrics |
| `review_creation_date` is date-only and is the **date the survey was sent**, not when the customer reviewed | all reviews | Stored as `review_survey_sent_date`; customer answer time is `review_answered_at` |
| Survey sent before delivery date | 4,976 measurable deliveries (95% of them late) | Flagged `survey_sent_before_delivery`; see `reports/eda_findings.md` §3.3 |
| Sparse edge months (2016-09 to 2016-12, 2018-09 to 2018-10) | 349 orders | Excluded from trends via `in_analysis_window` |

## 2. Mart tables

### `olist.fct_orders`: grain is one row per `order_id` (99,441 rows)

Items, payments and reviews are each aggregated to the order **before** joining, so
order-level values cannot be inflated by fan-out (enforced by `olist_reconcile_totals`).

| Column | Definition |
|---|---|
| `order_id` | Order key |
| `customer_id`, `customer_unique_id` | Order-level customer record / the person |
| `customer_state`, `customer_region` | Customer state and IBGE macro-region |
| `is_repeat_purchase` | The person had an earlier order |
| `order_status` | `created, approved, invoiced, processing, shipped, delivered, canceled, unavailable` |
| `purchased_at`, `purchase_date`, `purchase_month` | Purchase timestamp / date / month start |
| `in_analysis_window` | Purchase date between 2017-01-01 and 2018-08-31 (configurable) |
| `item_count` | Number of order lines (units) |
| `distinct_products`, `distinct_sellers` | |
| `has_items` | Order has at least one line |
| `primary_category` | English category of the most expensive line (`unknown` if none) |
| `items_value` | Σ item price (merchandise value) |
| `freight_value` | Σ freight charged to the customer |
| `order_gross_value` | `items_value + freight_value` |
| `payment_value` | Σ recorded payments for the order |
| `payment_records`, `max_installments` | |
| `primary_payment_type` | Method that covered the largest value (ties: alphabetical) |
| `used_voucher` | Any payment record is a voucher |
| `is_delivery_measurable` | `delivered` **and** a customer-delivery timestamp exists |
| `delivery_days` | Purchase to customer delivery, in fractional days |
| `estimated_delivery_days` | Purchase date to promised date |
| `delivery_delay_days` | Delivery date − promised date (positive = late) |
| `is_late` | Delivered after the promised date (date level) |
| `review_score` | Score (1–5) of the latest review; NULL if none |
| `review_survey_sent_date` | Date the satisfaction survey was sent (source `review_creation_date`) |
| `review_answered_at` | When the customer answered the survey |
| `review_count`, `review_has_comment` | |
| `is_low_review` | `review_score <= 2` (configurable) |
| `survey_sent_before_delivery` | Survey-sent date earlier than the delivery date |
| `answered_before_delivery` | Survey answered before the delivery timestamp |

### `olist.fct_order_items`: grain is `order_id, order_item_id` (112,650 rows)

Order lines with product category, seller location and order context (status, date,
customer region). Includes `line_gross_value = item_price + freight_value`.

### `olist.fct_order_payments`: grain is `order_id, payment_sequential` (103,886 rows)

Payment records with `payment_type`, `payment_installments`, `payment_value` and the
order's status and date.

### Dimensions

| Table | Grain | Rows | Notes |
|---|---|---:|---|
| `dim_customer` | `customer_id` | 99,441 | State, region, `customer_order_number` |
| `dim_product` | `product_id` | 32,951 | English category, weight, volume |
| `dim_seller` | `seller_id` | 3,095 | State, region |
| `dim_date` | `date` | 791 | 2016-09-01 to 2018-10-31 |
| `dim_geography` | `state_code` | 27 | State name and IBGE macro-region (static) |

## 3. Metric definitions (historical)

Values are **gross amounts paid by customers** (BRL). They are not Olist platform revenue,
because commissions and fees are not in the data.

| Metric | Definition | Population |
|---|---|---|
| Orders | `count(order_id)` | Stated per chart (all statuses unless noted) |
| Gross merchandise value (GMV) | Σ `items_value` | Orders with items |
| Gross order value | Σ `order_gross_value` (items + freight) | Orders with items |
| Payment value | Σ `payment_value` | All orders (includes 775 orders with payments but no items) |
| Average order value (AOV) | Σ `order_gross_value` / count of orders | `delivered` orders in the analysis window |
| Late-delivery rate | count(`is_late`) / count of measurable orders | `is_delivery_measurable` |
| Low-review rate | count(`is_low_review`) / count of reviewed orders | Orders with `review_score` |
| Payment-method mix | Share of orders by `primary_payment_type`, or share of payment value by `payment_type` | Stated per chart |

### Definition sensitivity

| Metric | Choice made | Alternative | Effect (measurable deliveries, analysis window) |
|---|---|---|---|
| Late delivery | Delivery **date** > promised date | Delivery **timestamp** > promised date 00:00 | 6.79% vs 8.13%; the 1.34 pp gap is orders delivered on the promised day |
| Review per order | Latest answered review | First review / average | Affects 547 orders with more than one review |
| AOV | Mean gross value of `delivered` orders | Median | Mean R$159.79 vs median R$105.28 (right-skewed) |

## 4. Python-vs-SQL reconciliation

`metrics/independent.py` recomputes 40 key metrics in pandas **directly from the raw
CSVs**: its own parser, its own joins and its own rule implementations, with no
warehouse reads. `metrics/sql_metrics.py` computes the same names from the marts.
`uv run python -m marketplace_analytics eda` fails if any metric differs. Counts and
cents must match exactly; ratios must agree to a relative 1e-9. The only things the two
sides share are the business definitions in this document (latest-review rule,
date-level lateness, analysis window, low-review threshold).

## 5. Power BI semantic model

The Power BI model (`powerbi/MarketplaceLab.SemanticModel`) imports one Parquet file
per table from `sql/powerbi/`. The real-data tables (`Orders`, `Order Items`,
`Payments`, `Date`, `Customer Region`, `Product Category`) are renamed views of the
marts above, using the same definitions. The `SIM *` tables are SIMULATED. Every
table, column and measure has a description in its TMDL file. See
[powerbi/README.md](../powerbi/README.md).
