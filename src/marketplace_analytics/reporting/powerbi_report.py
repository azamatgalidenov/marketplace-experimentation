"""Generate the PBIR pages of the Power BI report.

Visual, page and filter IDs are hashes of stable names, so re-running the generator
reproduces identical files. Layout: 1920x1080 canvas, 12x12 grid, 32px margin, 24px
gutter, 8px snap.

Only the `definition/pages` tree and the report-level filter are (re)written; the
scaffolded shell (`.pbip`, `.platform`, `definition.pbir`, `version.json`, theme) is
left as produced by `powerbi-report-author scaffold`.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "visualContainer/2.9.0/schema.json"
)
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
PAGES_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "pagesMetadata/1.1.0/schema.json"
)

CANVAS_W, CANVAS_H, MARGIN, GUTTER, SNAP, GRID = 1920, 1080, 32, 24, 8, 12
PAGE_BACKGROUND = "#F7F7F5"
SLICER_HEIGHT = 80
TEXT = "#0B0B0B"
TEXT_SECONDARY = "#52514E"
BLUE, GREEN, ORANGE, VIOLET = "#2A78D6", "#1BAF7A", "#EB6834", "#6250D6"
SIM_TINT, SIM_TEXT = "#E6E2FA", "#3B2E99"


def _id(*parts: str, n: int = 20) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:n]


def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def text_lit(value: str) -> dict:
    return lit("'" + value.replace("'", "''") + "'")


def num(value: float) -> dict:
    return lit(f"{value}D")


def color(hex_code: str) -> dict:
    return {"solid": {"color": text_lit(hex_code)}}


def column(table: str, name: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def measure(table: str, name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def projection(expr: dict) -> dict:
    inner = expr.get("Column") or expr.get("Measure")
    table, prop = inner["Expression"]["SourceRef"]["Entity"], inner["Property"]
    out = {"field": expr, "queryRef": f"{table}.{prop}", "nativeQueryRef": prop}
    if "_display" in expr:
        out["field"] = {k: v for k, v in expr.items() if k != "_display"}
        out["displayName"] = expr["_display"]
    return out


def named(expr: dict, display: str) -> dict:
    """Field expression with a shorter column header for tables."""
    return expr | {"_display": display}


def categorical_filter(scope: str, table: str, col: str, values: list[str]) -> dict:
    """In-list filter (literal values already encoded, e.g. "true" or "'positive'")."""
    return {
        "name": "Filter" + _id(scope, table, col, n=24),
        "field": column(table, col),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "f", "Entity": table, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": "f"}},
                                        "Property": col,
                                    }
                                }
                            ],
                            "Values": [[{"Literal": {"Value": v}}] for v in values],
                        }
                    }
                }
            ],
        },
        "howCreated": "User",
    }


def _snap(v: float) -> int:
    return int(round(v / SNAP) * SNAP)


CELL_W = (CANVAS_W - 2 * MARGIN - (GRID - 1) * GUTTER) / GRID
CELL_H = (CANVAS_H - 2 * MARGIN - (GRID - 1) * GUTTER) / GRID


def region_box(region: list[int], slot: int = 1, of: int = 1) -> dict:
    """Pixel box of a grid region [c0, r0, c1, r1) (1-indexed, end-exclusive);
    a slot divides the region along its longer axis."""
    c0, r0, c1, r1 = region
    x = MARGIN + (c0 - 1) * (CELL_W + GUTTER)
    y = MARGIN + (r0 - 1) * (CELL_H + GUTTER)
    w = (c1 - c0) * CELL_W + (c1 - c0 - 1) * GUTTER
    h = (r1 - r0) * CELL_H + (r1 - r0 - 1) * GUTTER
    if of > 1:
        if w >= h:
            sw = (w - (of - 1) * GUTTER) / of
            x, w = x + (slot - 1) * (sw + GUTTER), sw
        else:
            sh = (h - (of - 1) * GUTTER) / of
            y, h = y + (slot - 1) * (sh + GUTTER), sh
    sx, sy = _snap(x), _snap(y)
    sw = min(_snap(w), CANVAS_W - sx)
    sh = min(_snap(h), CANVAS_H - sy)
    return {"x": sx, "y": sy, "width": sw, "height": sh}


@dataclass
class Visual:
    id: str
    region: str
    body: dict
    slot: int = 1
    of: int = 1
    height: int | None = None  # override (e.g. slicers), else region/slot height


def _container(title: str | None, alt: str, extra: dict | None = None) -> dict:
    vco: dict = {
        "general": [{"properties": {"altText": text_lit(alt)}}],
        "visualHeader": [{"properties": {"show": lit("false")}}],
    }
    if title:
        vco["title"] = [
            {
                "properties": {
                    "show": lit("true"),
                    "text": text_lit(title),
                    "fontSize": num(12),
                    "bold": lit("true"),
                    "fontColor": color(TEXT),
                    "titleWrap": lit("true"),
                }
            }
        ]
        vco["subTitle"] = [{"properties": {"show": lit("false")}}]
    vco.update(extra or {})
    return vco


def title_box(text: str) -> dict:
    return {
        "visualType": "textbox",
        "objects": {
            "general": [
                {
                    "properties": {
                        "paragraphs": [
                            {
                                "textRuns": [
                                    {
                                        "value": text,
                                        "textStyle": {
                                            "fontFamily": "Segoe UI Semibold",
                                            "fontSize": "22px",
                                            "color": TEXT,
                                        },
                                    }
                                ],
                                "horizontalTextAlignment": "left",
                            }
                        ]
                    }
                }
            ]
        },
        "visualContainerObjects": {
            "background": [{"properties": {"show": lit("false")}}],
            "border": [{"properties": {"show": lit("false")}}],
            "padding": [{"properties": {k: num(0) for k in ("top", "bottom", "left", "right")}}],
            "general": [{"properties": {"altText": text_lit(text)}}],
        },
    }


def banner(text: str) -> dict:
    box = title_box(text)
    run = box["objects"]["general"][0]["properties"]["paragraphs"][0]["textRuns"][0]
    run["textStyle"] = {"fontFamily": "Segoe UI Semibold", "fontSize": "16px", "color": SIM_TEXT}
    box["visualContainerObjects"]["background"] = [
        {"properties": {"show": lit("true"), "color": color(SIM_TINT), "transparency": num(0)}}
    ]
    box["visualContainerObjects"]["padding"] = [
        {"properties": {"top": num(8), "bottom": num(8), "left": num(16), "right": num(16)}}
    ]
    return box


def slicer(table: str, col: str, header: str, sync: str, preselect: str | None = None) -> dict:
    objects: dict = {
        "data": [{"properties": {"mode": text_lit("Dropdown")}}],
        "header": [{"properties": {"show": lit("true"), "text": text_lit(header)}}],
    }
    if preselect is not None:
        objects["selection"] = [{"properties": {"strictSingleSelect": lit("true")}}]
        value = "'" + preselect + "'"
        objects["general"] = [
            {
                "properties": {
                    "filter": {
                        "filter": {
                            "Version": 2,
                            "From": [{"Name": "s", "Entity": table, "Type": 0}],
                            "Where": [
                                {
                                    "Condition": {
                                        "In": {
                                            "Expressions": [
                                                {
                                                    "Column": {
                                                        "Expression": {
                                                            "SourceRef": {"Source": "s"}
                                                        },
                                                        "Property": col,
                                                    }
                                                }
                                            ],
                                            "Values": [[{"Literal": {"Value": value}}]],
                                        }
                                    }
                                }
                            ],
                        }
                    }
                }
            }
        ]
    return {
        "visualType": "slicer",
        "syncGroup": {"groupName": sync, "fieldChanges": True, "filterChanges": True},
        "query": {"queryState": {"Values": {"projections": [projection(column(table, col))]}}},
        "objects": objects,
        "visualContainerObjects": {
            "padding": [{"properties": {k: num(8) for k in ("top", "bottom", "left", "right")}}],
            "general": [{"properties": {"altText": text_lit(f"{header} slicer")}}],
        },
    }


def cards(
    measures: list[tuple[str, str]], alt: str, value_size: int = 24, accent: str | None = None
) -> dict:
    objects = {
        "value": [
            {
                "properties": {
                    "fontSize": num(value_size),
                    "textWrap": lit("true"),
                    "labelDisplayUnits": lit("1D"),  # full numbers, no K/M abbreviation
                },
                "selector": {"id": "default"},
            }
        ],
        "label": [
            {
                "properties": {"fontSize": num(12), "textWrap": lit("true")},
                "selector": {"id": "default"},
            }
        ],
        "padding": [{"properties": {"paddingUniform": num(8)}, "selector": {"id": "default"}}],
        "layout": [{"properties": {"paddingUniform": num(0)}, "selector": {"id": "default"}}],
    }
    if accent:
        objects["value"][0]["properties"]["fontColor"] = color(accent)
    return {
        "visualType": "cardVisual",
        "query": {
            "queryState": {
                "Data": {"projections": [projection(measure(t, m)) for t, m in measures]}
            }
        },
        "objects": objects,
        "visualContainerObjects": _container(
            None,
            alt,
            {
                "padding": [
                    {"properties": {k: num(8) for k in ("top", "bottom", "left", "right")}}
                ],
                "background": [{"properties": {"show": lit("true"), "color": color("#FFFFFF")}}],
            },
        ),
    }


def text_card(table: str, meas: str, title: str, alt: str) -> dict:
    body = cards([(table, meas)], alt, value_size=13)
    body["objects"]["value"][0]["properties"]["fontColor"] = color(TEXT)
    body["objects"]["value"][0]["properties"]["horizontalAlignment"] = text_lit("left")
    body["objects"]["label"] = [
        {"properties": {"show": lit("false")}, "selector": {"id": "default"}}
    ]
    body["visualContainerObjects"] = _container(
        title,
        alt,
        {
            "padding": [{"properties": {k: num(12) for k in ("top", "bottom", "left", "right")}}],
            "background": [{"properties": {"show": lit("true"), "color": color("#FFFFFF")}}],
        },
    )
    return body


def chart(
    kind: str,
    category: dict,
    y: dict,
    title: str,
    alt: str,
    fill: str | None = None,
    series: dict | None = None,
    sort: tuple[dict, str] | None = None,
    labels: bool = False,
    filters: list[dict] | None = None,
    zero_axis: bool = False,
) -> dict:
    state = {
        "Category": {"projections": [projection(category)]},
        "Y": {"projections": [projection(y)]},
    }
    if series:
        state["Series"] = {"projections": [projection(series)]}
    query: dict = {"queryState": state}
    if sort:
        query["sortDefinition"] = {
            "sort": [{"field": sort[0], "direction": sort[1]}],
            "isDefaultSort": False,
        }
    objects: dict = {}
    if fill:
        objects["dataPoint"] = [{"properties": {"defaultColor": color(fill)}}]
    if labels:
        objects["labels"] = [{"properties": {"show": lit("true"), "fontSize": num(10)}}]
    if zero_axis:
        objects["valueAxis"] = [{"properties": {"start": num(0)}}]
    body = {
        "visualType": kind,
        "query": query,
        "objects": objects,
        "visualContainerObjects": _container(
            title,
            alt,
            {"background": [{"properties": {"show": lit("true"), "color": color("#FFFFFF")}}]},
        ),
    }
    if filters:
        body["filterConfig"] = {"filters": filters}
    return body


def table(
    kind: str,
    rows: list[dict],
    values: list[dict],
    title: str,
    alt: str,
    sort: tuple[dict, str] | None = None,
) -> dict:
    if kind == "pivotTable":
        state = {
            "Rows": {"projections": [projection(r) for r in rows]},
            "Values": {"projections": [projection(v) for v in values]},
        }
    else:  # tableEx with plain columns only
        state = {"Values": {"projections": [projection(c) for c in rows + values]}}
    query: dict = {"queryState": state}
    if sort:
        query["sortDefinition"] = {
            "sort": [{"field": sort[0], "direction": sort[1]}],
            "isDefaultSort": False,
        }
    return {
        "visualType": kind,
        "query": query,
        "objects": {
            "columnHeaders": [
                {
                    "properties": {
                        "columnAdjustment": text_lit("growToFit"),
                        "autoSizeColumnWidth": lit("true"),
                        "wordWrap": lit("true"),
                    }
                }
            ],
        },
        "visualContainerObjects": _container(
            title,
            alt,
            {"background": [{"properties": {"show": lit("true"), "color": color("#FFFFFF")}}]},
        ),
    }


ORD, PAY, ITM, DAT = "Orders", "Payments", "Order Items", "Date"
REG, CAT = "Customer Region", "Product Category"
USR, MET, SCN, SEG, DA, VM = (
    "SIM Experiment Users",
    "SIM Metric Results",
    "SIM Scenario",
    "SIM Segment Results",
    "SIM Daily Assignments",
    "SIM Variant Metrics",
)
PP, QC = "SIM Power Plan", "SIM Quality Checks"


@dataclass
class Page:
    key: str
    display_name: str
    regions: dict[str, list[int]]
    visuals: list[Visual] = field(default_factory=list)


def _p1() -> Page:
    p = Page(
        "executive",
        "Executive Overview",
        {
            "header": [1, 1, 9, 2],
            "filters": [9, 1, 13, 2],
            "kpis": [1, 2, 13, 4],
            "volume_trend": [1, 4, 8, 8],
            "payment_mix": [8, 4, 13, 8],
            "status_mix": [1, 8, 5, 13],
            "value_trend": [5, 8, 9, 13],
            "observations": [9, 8, 13, 13],
        },
    )
    p.visuals = [
        Visual(
            "page_title",
            "header",
            title_box(
                "How much did Olist sell, and how did customers pay? (real data, Jan 2017 to Aug 2018)"
            ),
        ),
        Visual("year_slicer", "filters", slicer(DAT, "Year", "Year", "YearSync"), 1, 2),
        Visual(
            "region_slicer", "filters", slicer(REG, "Region", "Customer region", "RegionSync"), 2, 2
        ),
        Visual(
            "kpis",
            "kpis",
            cards(
                [
                    (ORD, "Orders"),
                    (ORD, "Delivered Share"),
                    (ORD, "Delivered Gross Order Value"),
                    (ORD, "AOV (Delivered, Gross)"),
                    (PAY, "Payment Value"),
                ],
                "Headline totals: orders, delivered share, delivered gross order value, AOV and "
                "payment value for the selected period and region.",
            ),
        ),
        Visual(
            "orders_by_month",
            "volume_trend",
            chart(
                "columnChart",
                column(DAT, "Year Month"),
                measure(ORD, "Orders"),
                "Orders per month (all statuses)",
                "Column chart of order count by purchase month.",
                fill=BLUE,
            ),
        ),
        Visual(
            "payment_mix",
            "payment_mix",
            chart(
                "barChart",
                column(PAY, "Payment Type"),
                measure(PAY, "Payment Value Share"),
                "Share of payment value by method",
                "Bar chart of payment value share by payment method, largest first.",
                fill=GREEN,
                sort=(measure(PAY, "Payment Value Share"), "Descending"),
                labels=True,
            ),
        ),
        Visual(
            "status_mix",
            "status_mix",
            chart(
                "barChart",
                column(ORD, "Order Status"),
                measure(ORD, "Order Share"),
                "Share of orders by status",
                "Bar chart of order share by current order status.",
                fill=BLUE,
                sort=(measure(ORD, "Order Share"), "Descending"),
                labels=True,
            ),
        ),
        Visual(
            "value_by_month",
            "value_trend",
            chart(
                "lineChart",
                column(DAT, "Year Month"),
                measure(ORD, "Delivered Gross Order Value"),
                "Delivered gross order value per month (BRL, customer payments)",
                "Line chart of delivered gross order value by purchase month.",
                fill=GREEN,
            ),
        ),
        Visual(
            "observations",
            "observations",
            text_card(
                ORD,
                "Observations Text",
                "Observations (computed from the data)",
                "Computed observations: busiest month, top payment method, mean versus median "
                "order value.",
            ),
        ),
    ]
    return p


def _p2() -> Page:
    measurable = categorical_filter("p2_delay", ORD, "Is Delivery Measurable", ["true"])
    p = Page(
        "operations",
        "Historical Operations",
        {
            "header": [1, 1, 8, 2],
            "filters": [8, 1, 13, 2],
            "kpis": [1, 2, 13, 4],
            "late_trend": [1, 4, 7, 8],
            "review_by_delay": [7, 4, 13, 8],
            "review_dist": [1, 8, 4, 13],
            "region_table": [4, 8, 8, 13],
            "category_table": [8, 8, 13, 13],
        },
    )
    p.visuals = [
        Visual(
            "page_title",
            "header",
            title_box(
                "Where do deliveries miss the promise, and how do reviews respond? (real data, observational)"
            ),
        ),
        Visual("year_slicer", "filters", slicer(DAT, "Year", "Year", "YearSync"), 1, 3),
        Visual(
            "region_slicer", "filters", slicer(REG, "Region", "Customer region", "RegionSync"), 2, 3
        ),
        Visual(
            "category_slicer",
            "filters",
            slicer(CAT, "Category", "Product category", "CategorySync"),
            3,
            3,
        ),
        Visual(
            "kpis",
            "kpis",
            cards(
                [
                    (ORD, "Measurable Deliveries"),
                    (ORD, "Late Delivery Rate"),
                    (ORD, "Median Delivery Days"),
                    (ORD, "Low Review Rate"),
                    (ORD, "Low Review Gap Late vs On-time (pp)"),
                ],
                "Delivery and review KPIs; the last value is the low-review gap between late and "
                "on-time orders among surveys sent after delivery (observational).",
            ),
        ),
        Visual(
            "late_rate_by_month",
            "late_trend",
            chart(
                "lineChart",
                column(DAT, "Year Month"),
                measure(ORD, "Late Delivery Rate"),
                "Late-delivery rate by purchase month (measurable deliveries)",
                "Line chart of the share of deliveries after the promised date by month.",
                fill=ORANGE,
            ),
        ),
        Visual(
            "low_review_by_delay",
            "review_by_delay",
            chart(
                "columnChart",
                column(ORD, "Delay Bucket"),
                measure(ORD, "Low Review Rate"),
                "Low-review rate by days early or late (all surveys; observational)",
                "Column chart of the share of 1-2 star reviews by delivery delay bucket.",
                fill=ORANGE,
                sort=(column(ORD, "Delay Bucket"), "Ascending"),
                labels=True,
                filters=[measurable],
            ),
        ),
        Visual(
            "review_distribution",
            "review_dist",
            chart(
                "columnChart",
                column(ORD, "Review Score"),
                measure(ORD, "Review Score Share"),
                "Review score distribution",
                "Column chart of the share of reviewed orders by score 1 to 5.",
                fill=BLUE,
                sort=(column(ORD, "Review Score"), "Ascending"),
                labels=True,
            ),
        ),
        Visual(
            "region_comparison",
            "region_table",
            table(
                "pivotTable",
                [column(REG, "Region")],
                [
                    named(measure(ORD, "Measurable Deliveries"), "Deliveries"),
                    named(measure(ORD, "Median Delivery Days"), "Median days"),
                    named(measure(ORD, "Late Delivery Rate"), "Late rate"),
                    named(measure(ORD, "Low Review Rate"), "Low-review rate"),
                ],
                "Delivery and reviews by customer region",
                "Table comparing regions on deliveries, median delivery days, late rate and "
                "low-review rate.",
                sort=(measure(ORD, "Measurable Deliveries"), "Descending"),
            ),
        ),
        Visual(
            "category_comparison",
            "category_table",
            table(
                "pivotTable",
                [column(CAT, "Category")],
                [
                    named(measure(ITM, "Item GMV (Delivered)"), "Item value (delivered)"),
                    named(measure(ORD, "Late Delivery Rate"), "Late rate"),
                    named(measure(ORD, "Low Review Rate"), "Low-review rate"),
                ],
                "Categories: value (item level) and experience (primary category)",
                "Table of product categories with delivered item value, late rate and "
                "low-review rate.",
                sort=(measure(ITM, "Item GMV (Delivered)"), "Descending"),
            ),
        ),
    ]
    return p


SIM_REGIONS_HEADER = {
    "header": [1, 1, 9, 2],
    "filters": [9, 1, 13, 2],
    "sim_banner": [1, 2, 13, 3],
    "kpis": [1, 3, 13, 5],
}


def _p3() -> Page:
    p = Page(
        "sim_ab",
        "SIMULATED A/B Experiment",
        SIM_REGIONS_HEADER
        | {
            "completion": [1, 5, 6, 9],
            "decision": [6, 5, 13, 9],
            "results_table": [1, 9, 13, 13],
        },
    )
    p.visuals = [
        Visual(
            "page_title",
            "header",
            title_box(
                "SIMULATED checkout A/B test: what does each scenario show, and what do the "
                "pre-registered rules decide?"
            ),
        ),
        Visual(
            "scenario_slicer",
            "filters",
            slicer(SCN, "Scenario", "Scenario (SIMULATED)", "ScenarioSync", preselect="positive"),
        ),
        Visual(
            "sim_banner",
            "sim_banner",
            banner(
                "SIMULATED DATA: synthetic users and outcomes generated from documented "
                "assumptions. Not real business results; demonstrates the analysis method only."
            ),
        ),
        Visual(
            "kpis",
            "kpis",
            cards(
                [
                    (USR, "SIM Control Users"),
                    (USR, "SIM Treatment Users"),
                    (USR, "SIM Completion Control"),
                    (USR, "SIM Completion Treatment"),
                    (USR, "SIM Absolute Lift (pp)"),
                    (MET, "SIM Lift CI Label"),
                    (SCN, "SIM Decision"),
                ],
                "SIMULATED experiment KPIs: users per arm, completion per arm, absolute lift with "
                "95% confidence interval and p-value, and the pre-registered decision.",
                value_size=18,
                accent=VIOLET,
            ),
        ),
        Visual(
            "completion_by_variant",
            "completion",
            chart(
                "columnChart",
                column(USR, "Variant"),
                measure(USR, "SIM Completion Rate"),
                "SIMULATED purchase completion by variant (users assigned)",
                "Column chart of simulated purchase completion rate for control and treatment.",
                fill=VIOLET,
                sort=(column(USR, "Variant"), "Ascending"),
                labels=True,
            ),
        ),
        Visual(
            "decision_rationale",
            "decision",
            text_card(
                SCN,
                "SIM Decision Reasons",
                "Why the rules reached this decision (SIMULATED)",
                "Text explaining the pre-registered decision rule outcome for the selected "
                "simulated scenario.",
            ),
        ),
        Visual(
            "results_table",
            "results_table",
            table(
                "tableEx",
                [column(MET, "Metric"), column(MET, "Role"), column(MET, "Guardrail Status")],
                [
                    column(MET, "Control Value"),
                    column(MET, "Treatment Value"),
                    column(MET, "Absolute Difference"),
                    column(MET, "CI Low"),
                    column(MET, "CI High"),
                    column(MET, "Relative Difference"),
                    column(MET, "p-value"),
                ],
                "SIMULATED primary metric and guardrails vs pre-registered margins "
                "(rates as proportions; 95% CI)",
                "Table of simulated primary, guardrail and secondary metrics with control and "
                "treatment values, difference, confidence interval, p-value and guardrail status.",
                sort=(column(MET, "Metric"), "Ascending"),
            ),
        ),
    ]
    return p


def _p4() -> Page:
    p = Page(
        "sim_diagnostics",
        "SIMULATED Diagnostics",
        SIM_REGIONS_HEADER
        | {
            "segment_chart": [1, 5, 7, 10],
            "segment_table": [7, 5, 13, 10],
            "daily_alloc": [1, 10, 7, 13],
            "variant_metrics": [7, 10, 13, 13],
        },
    )
    p.visuals = [
        Visual(
            "page_title",
            "header",
            title_box(
                "SIMULATED diagnostics: is the split balanced, and are segment differences more "
                "than noise?"
            ),
        ),
        Visual(
            "scenario_slicer",
            "filters",
            slicer(SCN, "Scenario", "Scenario (SIMULATED)", "ScenarioSync", preselect="positive"),
        ),
        Visual(
            "sim_banner",
            "sim_banner",
            banner(
                "SIMULATED DATA: segment results are exploratory (Benjamini-Hochberg adjusted) and "
                "never justify a segment-only launch."
            ),
        ),
        Visual(
            "kpis",
            "kpis",
            cards(
                [
                    (USR, "SIM Assigned Users"),
                    (USR, "SIM Observed Treatment Share"),
                    (SCN, "SIM SRM Status"),
                    (PP, "SIM Achieved MDE (pp)"),
                    (QC, "SIM Quality Checks Passed"),
                    (MET, "SIM Lift Check"),
                ],
                "SIMULATED diagnostics: assigned users, treatment share, sample-ratio-mismatch "
                "status, achieved minimum detectable effect, data-quality checks and DAX vs Python "
                "consistency.",
                value_size=18,
                accent=VIOLET,
            ),
        ),
        Visual(
            "segment_lift",
            "segment_chart",
            chart(
                "barChart",
                column(SEG, "Segment"),
                measure(SEG, "SIM Segment Lift (pp)"),
                "SIMULATED lift by pre-registered segment (pp, exploratory)",
                "Bar chart of simulated completion lift within each device and customer-type "
                "segment.",
                fill=VIOLET,
                sort=(column(SEG, "Segment"), "Ascending"),
                labels=True,
            ),
        ),
        Visual(
            "segment_table",
            "segment_table",
            table(
                "tableEx",
                [column(SEG, "Segment"), column(SEG, "Small Sample")],
                [
                    column(SEG, "Treatment Users"),
                    column(SEG, "Control Users"),
                    column(SEG, "CI Low"),
                    column(SEG, "CI High"),
                    column(SEG, "BH Adjusted p-value"),
                ],
                "Segment uncertainty: 95% CI (proportion points), BH-adjusted p, small-sample flag",
                "Table of simulated segment results with users per arm, confidence interval, "
                "Benjamini-Hochberg adjusted p-value and small-sample flag.",
                sort=(column(SEG, "Segment"), "Ascending"),
            ),
        ),
        Visual(
            "daily_allocation",
            "daily_alloc",
            chart(
                "lineChart",
                column(DA, "Exposure Date"),
                measure(DA, "SIM Daily New Users"),
                "SIMULATED new users per day by variant",
                "Line chart of daily new assigned users for control and treatment.",
                series=column(DA, "Variant"),
                zero_axis=True,
            ),
        ),
        Visual(
            "variant_metrics",
            "variant_metrics",
            table(
                "tableEx",
                [column(VM, "Variant")],
                [
                    column(VM, "Assigned Users"),
                    column(VM, "Purchase Completion Rate"),
                    column(VM, "Net Order Value per User"),
                    column(VM, "Checkout Error Rate"),
                    column(VM, "Cancellation Rate"),
                ],
                "SIMULATED per-variant metric values (SQL, no inference)",
                "Table of simulated per-variant assigned users, completion, net order value per "
                "user, checkout error rate and cancellation rate.",
                sort=(column(VM, "Variant"), "Ascending"),
            ),
        ),
    ]
    return p


PAGES = (_p1, _p2, _p3, _p4)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_pages() -> list[Page]:
    return [f() for f in PAGES]


def generate_report(report_dir: Path) -> list[Page]:
    definition = report_dir / "definition"
    pages_dir = definition / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages = build_pages()
    for page in pages:
        page_id = _id("page", page.key)
        page_json = {
            "$schema": PAGE_SCHEMA,
            "name": page_id,
            "displayName": page.display_name,
            "displayOption": "FitToPage",
            "height": CANVAS_H,
            "width": CANVAS_W,
            "objects": {
                "background": [
                    {"properties": {"color": color(PAGE_BACKGROUND), "transparency": num(0)}}
                ]
            },
        }
        _write(pages_dir / page_id / "page.json", page_json)
        for z, visual in enumerate(page.visuals, start=1):
            box = region_box(page.regions[visual.region], visual.slot, visual.of)
            if visual.body["visualType"] == "slicer":
                # 60px chrome + 8/8 padding; extends into the gutter above the next row.
                box["height"] = SLICER_HEIGHT
            vid = _id(page.key, visual.id)
            _write(
                pages_dir / page_id / "visuals" / vid / "visual.json",
                {
                    "$schema": VISUAL_SCHEMA,
                    "name": vid,
                    "position": box | {"z": z * 1000, "tabOrder": z * 1000},
                    "visual": {k: v for k, v in visual.body.items() if k != "filterConfig"},
                    **(
                        {"filterConfig": visual.body["filterConfig"]}
                        if "filterConfig" in visual.body
                        else {}
                    ),
                },
            )
    page_ids = [_id("page", p.key) for p in pages]
    _write(
        pages_dir / "pages.json",
        {"$schema": PAGES_SCHEMA, "pageOrder": page_ids, "activePageName": page_ids[0]},
    )

    # Report-level filter: historical analysis window (Date is unrelated to SIM tables).
    report_path = definition / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["filterConfig"] = {
        "filters": [categorical_filter("report", DAT, "In Analysis Window", ["true"])]
    }
    _write(report_path, report)
    return pages


def layout_audit(page: Page) -> dict:
    """Space audit of the grid regions (content cells exclude the header row)."""
    content_cells = GRID * GRID - GRID  # row 1 is the header/filter band
    used = set()
    for name, (c0, r0, c1, r1) in page.regions.items():
        if name in ("header", "filters"):
            continue
        for c in range(c0, c1):
            for r in range(r0, r1):
                used.add((c, r))
    placed = {v.region for v in page.visuals}
    return {
        "content_cells": content_cells,
        "placed_cells": len(used),
        "empty_pct": math.floor(100 * (content_cells - len(used)) / content_cells),
        "unplaced_regions": sorted(set(page.regions) - placed),
    }
