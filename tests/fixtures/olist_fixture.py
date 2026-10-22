"""A tiny, hand-made Olist-shaped dataset for pipeline tests.

This is a test fixture, not real Olist data. It contains the edge cases
seen in the real dataset, and its expected values can be computed by hand:

* o1: delivered on time, 2 items in 2 categories, paid with credit card + voucher,
      two reviews (the latest one, score 1, must win).
* o2: delivered late, same person (customer_unique_id u1) as o1 -> repeat purchase,
      re-uses review_id r1 (review_id is not unique in the source).
* o3: canceled outside the analysis window, no items, no payments, no review.
* o4: shipped (not delivered), product with no category, paid by debit card.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROWS: dict[str, tuple[list[str], list[list[str]]]] = {
    "olist_orders_dataset.csv": (
        [
            "order_id",
            "customer_id",
            "order_status",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
        [
            [
                "o1",
                "c1",
                "delivered",
                "2017-03-01 10:00:00",
                "2017-03-01 11:00:00",
                "2017-03-02 09:00:00",
                "2017-03-08 10:00:00",
                "2017-03-10 00:00:00",
            ],
            [
                "o2",
                "c2",
                "delivered",
                "2017-04-01 08:00:00",
                "2017-04-01 09:00:00",
                "2017-04-03 09:00:00",
                "2017-04-20 12:00:00",
                "2017-04-15 00:00:00",
            ],
            ["o3", "c3", "canceled", "2018-09-15 12:00:00", "", "", "", "2018-10-01 00:00:00"],
            [
                "o4",
                "c4",
                "shipped",
                "2018-01-10 15:30:00",
                "2018-01-10 16:00:00",
                "2018-01-12 10:00:00",
                "",
                "2018-02-01 00:00:00",
            ],
        ],
    ),
    "olist_order_items_dataset.csv": (
        [
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ],
        [
            ["o1", "1", "p1", "s1", "2017-03-05 10:00:00", "100.00", "10.00"],
            ["o1", "2", "p2", "s2", "2017-03-05 10:00:00", "50.00", "5.00"],
            ["o2", "1", "p1", "s1", "2017-04-05 08:00:00", "200.00", "20.00"],
            ["o4", "1", "p3", "s2", "2018-01-15 15:30:00", "80.00", "12.50"],
        ],
    ),
    "olist_order_payments_dataset.csv": (
        ["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"],
        [
            ["o1", "1", "credit_card", "3", "100.00"],
            ["o1", "2", "voucher", "1", "65.00"],
            ["o2", "1", "boleto", "1", "220.00"],
            ["o4", "1", "debit_card", "1", "92.50"],
        ],
    ),
    "olist_order_reviews_dataset.csv": (
        [
            "review_id",
            "order_id",
            "review_score",
            "review_comment_title",
            "review_comment_message",
            "review_creation_date",
            "review_answer_timestamp",
        ],
        [
            ["r1", "o1", "5", "", "", "2017-03-08 00:00:00", "2017-03-09 10:00:00"],
            ["r2", "o1", "1", "", "produto errado", "2017-03-11 00:00:00", "2017-03-12 10:00:00"],
            ["r1", "o2", "4", "", "", "2017-04-21 00:00:00", "2017-04-22 10:00:00"],
            ["r4", "o4", "2", "", "", "2018-02-02 00:00:00", "2018-02-03 10:00:00"],
        ],
    ),
    "olist_customers_dataset.csv": (
        [
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ],
        [
            ["c1", "u1", "01001", "sao paulo", "SP"],
            ["c2", "u1", "20000", "rio de janeiro", "RJ"],
            ["c3", "u3", "30000", "belo horizonte", "MG"],
            ["c4", "u4", "40000", "salvador", "BA"],
        ],
    ),
    "olist_products_dataset.csv": (
        [
            "product_id",
            "product_category_name",
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ],
        [
            ["p1", "cama_mesa_banho", "40", "500", "2", "1000", "20", "10", "15"],
            ["p2", "pc_gamer", "30", "300", "1", "2000", "30", "20", "10"],
            ["p3", "", "", "", "", "500", "10", "10", "10"],
        ],
    ),
    "olist_sellers_dataset.csv": (
        ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
        [
            ["s1", "01002", "sao paulo", "SP"],
            ["s2", "80000", "curitiba", "PR"],
        ],
    ),
    "product_category_name_translation.csv": (
        ["product_category_name", "product_category_name_english"],
        [["cama_mesa_banho", "bed_bath_table"]],
    ),
}


def write_olist_fixture(raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for file_name, (header, rows) in ROWS.items():
        with open(raw_dir / file_name, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
    return raw_dir
