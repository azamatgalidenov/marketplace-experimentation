"""Compare independently computed metrics with SQL metrics."""

from __future__ import annotations

import math

import pandas as pd

# Counts and cents must match exactly; ratios and means within floating-point noise.
FLOAT_REL_TOL = 1e-9


def reconcile(python_metrics: dict[str, float], sql_metrics: dict[str, float]) -> pd.DataFrame:
    """Return one row per metric with both values and whether they agree.

    Metrics present on only one side are reported as mismatches rather than dropped.
    """
    rows = []
    for name in sorted(set(python_metrics) | set(sql_metrics)):
        py, sq = python_metrics.get(name), sql_metrics.get(name)
        if py is None or sq is None:
            match = False
        elif isinstance(py, float) or isinstance(sq, float):
            match = math.isclose(float(py), float(sq), rel_tol=FLOAT_REL_TOL, abs_tol=1e-12)
        else:
            match = int(py) == int(sq)
        diff = (float(sq) - float(py)) if py is not None and sq is not None else math.nan
        rows.append({"metric": name, "python": py, "sql": sq, "difference": diff, "match": match})
    return pd.DataFrame(rows)
