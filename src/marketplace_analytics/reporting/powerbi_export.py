"""Export warehouse tables to Parquet for the Power BI semantic model.

Each file in ``sql/powerbi`` is one Power BI table: ``hist_*`` from the real Olist marts,
``sim_*`` from the SIMULATED experiment. The simulation's true parameters are never
exported. A manifest with row counts is written alongside the files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb

from marketplace_analytics.config import SQL_DIR, Settings
from marketplace_analytics.data.warehouse import connect, run_quality_checks, set_variables

logger = logging.getLogger(__name__)

EXPORT_SQL_DIR = SQL_DIR / "powerbi"
FORBIDDEN = ("simulation_truth", "true_")


class PowerBIExportError(RuntimeError):
    """The warehouse is missing tables the report needs."""


def export_powerbi(settings: Settings, out_dir: Path | None = None) -> dict[str, int]:
    out_dir = out_dir or settings.paths.powerbi_export_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    con = connect(settings.paths.warehouse)
    counts: dict[str, int] = {}
    try:
        set_variables(con, settings)
        for path in sorted(EXPORT_SQL_DIR.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            if any(token in sql for token in FORBIDDEN):
                raise PowerBIExportError(f"{path.name} would export simulation truth")
            counts[path.stem] = _copy(con, sql, out_dir / f"{path.stem}.parquet", path.stem)
        # Current data-quality status of the simulated tables.
        checks = run_quality_checks(con, prefix="sim_", raise_on_error=False)
        con.execute(
            "CREATE OR REPLACE TEMP TABLE _checks AS SELECT * FROM (VALUES "
            + ", ".join(
                f"('{c.name}', '{c.severity}', {c.failing_rows}, {str(c.passed).upper()})"
                for c in checks
            )
            + ") AS t(check_name, severity, failing_rows, passed)"
        )
        counts["sim_quality_checks"] = _copy(
            con,
            "SELECT * FROM _checks",
            out_dir / "sim_quality_checks.parquet",
            "sim_quality_checks",
        )
    finally:
        con.close()
    (out_dir / "manifest.json").write_text(json.dumps(counts, indent=2))
    logger.info("Exported %d Power BI tables to %s", len(counts), out_dir)
    return counts


def _copy(con: duckdb.DuckDBPyConnection, sql: str, target: Path, name: str) -> int:
    try:
        n = con.execute(f"SELECT count(*) FROM ({sql.rstrip().rstrip(';')})").fetchone()[0]
        con.execute(f"COPY ({sql.rstrip().rstrip(';')}) TO '{target.as_posix()}' (FORMAT parquet)")
    except duckdb.CatalogException as exc:
        hint = "run `experiment`" if name.startswith("sim") else "run `build`"
        raise PowerBIExportError(f"Cannot export {name}: {exc}. Did you {hint} first?") from exc
    logger.info("Exported %s: %d rows", name, n)
    return int(n)
