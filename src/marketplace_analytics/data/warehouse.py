"""Build the DuckDB warehouse: load raw CSVs, run SQL transformations, run quality checks.

Layers (schemas):
    raw    - Olist CSVs loaded as all-VARCHAR, untouched.
    stg    - Typed, renamed views over raw (one per source table).
    olist  - Historical marts (facts and dimensions) built from real Olist data.
    sim    - SIMULATED experiment tables (built separately; never mixed with olist).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

from marketplace_analytics.config import SQL_DIR, Settings
from marketplace_analytics.data.download import OLIST_FILES, REQUIRED_TABLES, ensure_raw_data

logger = logging.getLogger(__name__)

SCHEMAS = ("raw", "stg", "olist", "sim")
OLIST_LAYERS = ("staging", "marts")


@dataclass(frozen=True)
class CheckResult:
    name: str
    description: str
    severity: str  # "error" or "warn"
    failing_rows: int

    @property
    def passed(self) -> bool:
        return self.failing_rows == 0


class DataQualityError(RuntimeError):
    """Raised when one or more error-severity quality checks fail."""


def connect(path: Path | str) -> duckdb.DuckDBPyConnection:
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path = str(path)
    con = duckdb.connect(path)
    for schema in SCHEMAS:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    return con


def set_variables(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    """Expose configuration values to SQL through DuckDB session variables."""
    olist = settings.olist
    con.execute(f"SET VARIABLE analysis_start = DATE '{olist['analysis_start']}'")
    con.execute(f"SET VARIABLE analysis_end = DATE '{olist['analysis_end']}'")
    con.execute(f"SET VARIABLE low_review_max_score = {int(olist['low_review_max_score'])}")


def load_raw_olist(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> dict[str, int]:
    """Load each required Olist CSV into ``raw.olist_<table>`` as text columns."""
    ensure_raw_data(raw_dir)
    counts = {}
    for table in REQUIRED_TABLES:
        csv_path = (raw_dir / OLIST_FILES[table]).as_posix()
        con.execute(
            f"CREATE OR REPLACE TABLE raw.olist_{table} AS "
            "SELECT * FROM read_csv(?, header = true, all_varchar = true)",
            [csv_path],
        )
        counts[table] = con.execute(f"SELECT count(*) FROM raw.olist_{table}").fetchone()[0]
        logger.info("Loaded raw.olist_%s: %d rows", table, counts[table])
    return counts


def sql_files(layer: str, sql_dir: Path = SQL_DIR) -> list[Path]:
    files = sorted((sql_dir / layer).glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"No SQL files found in {sql_dir / layer}")
    return files


def run_sql_layer(con: duckdb.DuckDBPyConnection, layer: str, sql_dir: Path = SQL_DIR) -> None:
    for path in sql_files(layer, sql_dir):
        logger.info("Running %s/%s", layer, path.name)
        try:
            con.execute(path.read_text(encoding="utf-8"))
        except duckdb.Error as exc:
            raise RuntimeError(f"SQL failed in {path.relative_to(sql_dir)}: {exc}") from exc


_HEADER = re.compile(r"^--\s*(description|severity):\s*(.+)$", re.MULTILINE)


def run_quality_checks(
    con: duckdb.DuckDBPyConnection,
    prefix: str = "",
    sql_dir: Path = SQL_DIR,
    raise_on_error: bool = True,
) -> list[CheckResult]:
    """Run every check in sql/quality_checks whose file name starts with ``prefix``.

    A check is a SELECT returning the rows that violate a rule, so zero rows means pass.
    """
    results = []
    for path in sorted((sql_dir / "quality_checks").glob(f"{prefix}*.sql")):
        text = path.read_text(encoding="utf-8")
        header = dict(_HEADER.findall(text))
        severity = header.get("severity", "error").strip()
        failing = con.execute(f"SELECT count(*) FROM ({text.rstrip().rstrip(';')})").fetchone()[0]
        result = CheckResult(path.stem, header.get("description", "").strip(), severity, failing)
        results.append(result)
        log = (
            logger.info
            if result.passed
            else (logger.warning if severity == "warn" else logger.error)
        )
        log(
            "[%s] %s (%s): %d failing rows",
            "PASS" if result.passed else "FAIL",
            result.name,
            severity,
            failing,
        )

    failed = [r for r in results if not r.passed and r.severity == "error"]
    if failed and raise_on_error:
        names = ", ".join(r.name for r in failed)
        raise DataQualityError(f"{len(failed)} data-quality check(s) failed: {names}")
    return results


def build_olist(settings: Settings, raw_dir: Path | None = None) -> list[CheckResult]:
    """Full historical build: raw load -> staging -> marts -> quality checks."""
    raw_dir = raw_dir or settings.paths.raw_dir
    con = connect(settings.paths.warehouse)
    try:
        set_variables(con, settings)
        load_raw_olist(con, raw_dir)
        for layer in OLIST_LAYERS:
            run_sql_layer(con, layer)
        return run_quality_checks(con, prefix="olist_")
    finally:
        con.close()
