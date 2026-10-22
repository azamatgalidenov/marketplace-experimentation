from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.olist_fixture import write_olist_fixture  # noqa: E402

from marketplace_analytics.config import Settings, load_settings  # noqa: E402
from marketplace_analytics.data.warehouse import build_olist, connect, set_variables  # noqa: E402


@pytest.fixture(scope="session")
def fixture_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Settings whose paths all point at a temporary directory."""
    root = tmp_path_factory.mktemp("repo")
    settings = load_settings(root=root)
    write_olist_fixture(settings.paths.raw_dir)
    return settings


@pytest.fixture(scope="session")
def built_fixture_warehouse(fixture_settings: Settings) -> Settings:
    build_olist(fixture_settings)
    return fixture_settings


@pytest.fixture
def fixture_con(built_fixture_warehouse: Settings):
    """Read-write connection to a *copy* of the fixture warehouse, safe to mutate."""
    con = duckdb.connect()
    con.execute(f"ATTACH '{built_fixture_warehouse.paths.warehouse.as_posix()}' AS src (READ_ONLY)")
    con.execute("COPY FROM DATABASE src TO memory")
    con.execute("DETACH src")
    set_variables(con, built_fixture_warehouse)
    yield con
    con.close()


@pytest.fixture
def fixture_ro_con(built_fixture_warehouse: Settings):
    con = connect(built_fixture_warehouse.paths.warehouse)
    yield con
    con.close()
