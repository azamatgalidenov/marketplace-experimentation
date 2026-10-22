"""Configuration loading and repository paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "settings.yaml"
SQL_DIR = REPO_ROOT / "sql"


@dataclass(frozen=True)
class Paths:
    raw_dir: Path
    processed_dir: Path
    warehouse: Path
    figures_dir: Path
    results_dir: Path
    powerbi_export_dir: Path


@dataclass(frozen=True)
class Settings:
    paths: Paths
    raw: dict[str, Any]

    @property
    def olist(self) -> dict[str, Any]:
        return self.raw["olist"]

    def section(self, name: str) -> dict[str, Any]:
        if name not in self.raw:
            raise KeyError(f"Missing section '{name}' in configuration")
        return self.raw[name]


def load_settings(config_path: Path | None = None, root: Path | None = None) -> Settings:
    """Load settings from YAML. Relative paths resolve against ``root`` (default: repo root)."""
    config_path = config_path or DEFAULT_CONFIG_PATH
    root = root or REPO_ROOT
    with open(config_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    paths = Paths(**{key: (root / value) for key, value in raw["paths"].items()})
    return Settings(paths=paths, raw=raw)
