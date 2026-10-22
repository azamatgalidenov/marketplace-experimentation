"""Power BI artifacts: semantic model (TMDL), report generator (PBIR) and Parquet export.

Runs without Power BI Desktop: name clashes that stop the model loading, visuals bound
to missing fields, generator determinism, and the export (every table the model reads
exists with the columns it maps, and no simulation truth is exported).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import duckdb
import pytest
from fixtures.olist_fixture import write_olist_fixture

from marketplace_analytics.config import REPO_ROOT, load_settings
from marketplace_analytics.data.warehouse import build_olist
from marketplace_analytics.reporting import powerbi_export
from marketplace_analytics.reporting.experiment import run_experiment
from marketplace_analytics.reporting.powerbi_export import PowerBIExportError, export_powerbi
from marketplace_analytics.reporting.powerbi_report import (
    CANVAS_H,
    CANVAS_W,
    build_pages,
    generate_report,
    layout_audit,
)

POWERBI = REPO_ROOT / "powerbi"
TABLES_DIR = POWERBI / "MarketplaceLab.SemanticModel" / "definition" / "tables"
REPORT_DIR = POWERBI / "MarketplaceLab.Report"

_OBJECT = re.compile(r"^\t(column|measure) ('(?:[^']|'')+'|[^\s=]+)")
_TABLE = re.compile(r"^table ('(?:[^']|'')+'|\S+)")
_SOURCE_COLUMN = re.compile(r"^\t\tsourceColumn: (\S+)")
_PARQUET = re.compile(r'"\\([a-z_]+)\.parquet"')


def _unquote(name: str) -> str:
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


def _parse_tmdl() -> dict[str, dict]:
    """Table -> columns, measures, source columns and the Parquet file it loads."""
    model = {}
    for path in sorted(TABLES_DIR.glob("*.tmdl")):
        table = {"columns": [], "measures": [], "source_columns": [], "parquet": None}
        name = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if m := _TABLE.match(line):
                name = _unquote(m.group(1))
            elif m := _OBJECT.match(line):
                table[f"{m.group(1)}s"].append(_unquote(m.group(2)))
            elif m := _SOURCE_COLUMN.match(line):
                table["source_columns"].append(m.group(1))
            elif m := _PARQUET.search(line):
                table["parquet"] = m.group(1)
        assert name, path
        model[name] = table
    return model


@pytest.fixture(scope="module")
def model() -> dict[str, dict]:
    return _parse_tmdl()


def test_model_parses_all_tables(model):
    assert len(model) == 14
    assert sum(len(t["measures"]) for t in model.values()) >= 40
    assert all(t["parquet"] for t in model.values())


def test_no_measure_column_name_clash(model):
    """A measure named like a column (any table) stops the model loading in Desktop."""
    measures = [m for t in model.values() for m in t["measures"]]
    assert len(measures) == len(set(measures)), "duplicate measure names"
    for table, t in model.items():
        clash = set(t["columns"]) & set(measures)
        assert not clash, f"{table}: measure/column name clash {clash}"
        assert len(t["columns"]) == len(set(t["columns"])), table


def test_tables_are_labelled_by_source(model):
    """SIMULATED tables are prefixed SIM and load only sim_* exports; real tables hist_*."""
    for table, t in model.items():
        prefix = "sim_" if table.startswith("SIM ") else "hist_"
        assert t["parquet"].startswith(prefix), table
    sim_tmdl = " ".join(
        p.read_text(encoding="utf-8") for p in TABLES_DIR.glob("SIM *.tmdl")
    ).lower()
    assert "simulation_truth" not in sim_tmdl and "true_" not in sim_tmdl


def test_relationships_reference_existing_columns(model):
    rel = (TABLES_DIR.parent / "relationships.tmdl").read_text(encoding="utf-8")
    ends = re.findall(r"(?:from|to)Column: ('(?:[^']|'')+'|[^.\s]+)\.('(?:[^']|'')+'|\S+)", rel)
    assert len(ends) == 2 * len(re.findall(r"^relationship ", rel, re.M)) > 0
    for table, col in ends:
        assert _unquote(col) in model[_unquote(table)]["columns"], (table, col)
    for frm, to in zip(ends[::2], ends[1::2], strict=True):
        assert frm[0].startswith("'SIM ") == to[0].startswith("'SIM "), (frm, to)


def test_every_parquet_has_an_export_query(model):
    exported = {p.stem for p in powerbi_export.EXPORT_SQL_DIR.glob("*.sql")} | {
        "sim_quality_checks"
    }
    assert {t["parquet"] for t in model.values()} == exported


def _fields(node, out: set) -> set:
    if isinstance(node, dict):
        for kind in ("Column", "Measure"):
            ref = node.get(kind)
            if isinstance(ref, dict) and "Entity" in ref.get("Expression", {}).get("SourceRef", {}):
                out.add((kind, ref["Expression"]["SourceRef"]["Entity"], ref["Property"]))
        for v in node.values():
            _fields(v, out)
    elif isinstance(node, list):
        for v in node:
            _fields(v, out)
    return out


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    """The generator run twice into a copy of the scaffolded report."""
    target = tmp_path_factory.mktemp("pbir") / "MarketplaceLab.Report"
    shutil.copytree(REPORT_DIR, target)
    generate_report(target)
    first = {p.relative_to(target): p.read_bytes() for p in target.rglob("*.json")}
    generate_report(target)
    second = {p.relative_to(target): p.read_bytes() for p in target.rglob("*.json")}
    assert first == second, "generator output is not deterministic"
    return target


def test_generated_report_matches_committed_report(generated):
    """The committed PBIR is exactly what `powerbi-report` produces (no hand edits)."""
    for path in (generated / "definition").rglob("*.json"):
        committed = REPORT_DIR / path.relative_to(generated)
        assert committed.exists(), committed
        assert committed.read_bytes() == path.read_bytes(), committed


def test_visuals_bind_only_existing_fields(generated, model):
    files = list((generated / "definition").rglob("*.json"))
    refs: set = set()
    for path in files:
        _fields(json.loads(path.read_text(encoding="utf-8")), refs)
    assert refs
    for kind, table, prop in refs:
        assert table in model, table
        pool = model[table]["measures" if kind == "Measure" else "columns"]
        assert prop in pool, f"{kind} {table}[{prop}] is not in the model"


def test_pages_layout_is_complete_and_on_canvas(generated):
    pages = build_pages()
    assert [p.display_name for p in pages] == [
        "Executive Overview",
        "Historical Operations",
        "SIMULATED A/B Experiment",
        "SIMULATED Diagnostics",
    ]
    for page in pages:
        assert layout_audit(page)["unplaced_regions"] == [], page.key
    for path in (generated / "definition" / "pages").rglob("visual.json"):
        pos = json.loads(path.read_text(encoding="utf-8"))["position"]
        assert pos["x"] >= 0 and pos["y"] >= 0
        assert pos["x"] + pos["width"] <= CANVAS_W and pos["y"] + pos["height"] <= CANVAS_H


def test_sim_pages_use_only_sim_tables_and_carry_banner(generated):
    pages_dir = generated / "definition" / "pages"
    for page_dir in (d for d in pages_dir.iterdir() if d.is_dir()):
        name = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))["displayName"]
        texts = [p.read_text(encoding="utf-8") for p in page_dir.rglob("visual.json")]
        tables = set()
        for t in texts:
            tables |= {e for _, e, _ in _fields(json.loads(t), set())}
        if name.startswith("SIMULATED"):
            assert tables and all(t.startswith("SIM ") for t in tables), (name, tables)
            assert any("SIMULATED" in t and "textbox" in t for t in texts), name
        else:
            assert not any(t.startswith("SIM ") for t in tables), (name, tables)


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    settings = load_settings(root=tmp_path_factory.mktemp("repo"))
    write_olist_fixture(settings.paths.raw_dir)
    build_olist(settings)
    settings.raw["experiment"]["validation"]["srm_logging_losses"] = [0.10]
    run_experiment(settings, replications=5, n_users=2000)
    out = settings.paths.powerbi_export_dir
    return export_powerbi(settings), out


def test_export_writes_every_model_table(exported, model):
    counts, out = exported
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest == counts
    for table, t in model.items():
        path = out / f"{t['parquet']}.parquet"
        assert path.exists(), table
        cols = set(duckdb.sql(f"DESCRIBE SELECT * FROM '{path.as_posix()}'").df()["column_name"])
        missing = set(t["source_columns"]) - cols
        assert not missing, f"{table}: model maps columns the export lacks {missing}"
        assert not any(c.startswith("true_") for c in cols), table
    assert counts["sim_fct_experiment_users"] == 2000 * counts["sim_dim_scenario"]
    assert counts["hist_fct_orders"] > 0


def test_export_refuses_simulation_truth(tmp_path, monkeypatch):
    (tmp_path / "sim_leak.sql").write_text("SELECT * FROM sim.simulation_truth_validation_only")
    monkeypatch.setattr(powerbi_export, "EXPORT_SQL_DIR", tmp_path)
    settings = load_settings(root=tmp_path / "repo")
    with pytest.raises(PowerBIExportError, match="simulation truth"):
        export_powerbi(settings, out_dir=tmp_path / "out")
