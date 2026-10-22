"""Command-line entry point: ``uv run python -m marketplace_analytics <command>``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from marketplace_analytics.config import REPO_ROOT, load_settings
from marketplace_analytics.data.download import MissingRawDataError, download_olist
from marketplace_analytics.data.warehouse import DataQualityError, build_olist
from marketplace_analytics.reporting.eda import ReconciliationError, run_eda
from marketplace_analytics.reporting.experiment import (
    ExperimentReconciliationError,
    run_experiment,
)
from marketplace_analytics.reporting.experiment_regression import (
    ExperimentRegressionError,
    run_experiment_regression,
)
from marketplace_analytics.reporting.powerbi_export import PowerBIExportError, export_powerbi
from marketplace_analytics.reporting.powerbi_report import generate_report
from marketplace_analytics.reporting.regression import run_regression

logger = logging.getLogger("marketplace_analytics")


def _download(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    olist = settings.olist
    download_olist(
        settings.paths.raw_dir,
        olist["download_url"],
        olist.get("expected_zip_sha256"),
        force=args.force,
    )


def _build(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    results = build_olist(settings)
    passed = sum(r.passed for r in results)
    logger.info(
        "Warehouse built at %s (%d/%d checks passed)",
        settings.paths.warehouse,
        passed,
        len(results),
    )


def _eda(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    result = run_eda(settings)
    logger.info("EDA complete: %d charts, %d tables", len(result.figures), len(result.tables))


def _regression(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    result = run_regression(settings)
    logger.info("Regression complete: %d specifications", len(result.fits))


def _experiment(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    result = run_experiment(settings, replications=args.replications)
    for scenario, decision in result.key_numbers["decisions"].items():
        logger.info("SIMULATED scenario %-15s -> %s", scenario, decision)


def _experiment_regression(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    result = run_experiment_regression(settings, replications=args.replications)
    for scenario, p in result.key_numbers["interaction_p_values"].items():
        logger.info("SIMULATED %-15s treatment x device LR p = %.3f", scenario, p)


def _export_powerbi(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    counts = export_powerbi(settings)
    logger.info("Power BI export complete: %d tables", len(counts))


def _powerbi_report(args: argparse.Namespace) -> None:
    report_dir = REPO_ROOT / "powerbi" / "MarketplaceLab.Report"
    pages = generate_report(report_dir)
    logger.info(
        "Generated %d pages / %d visuals in %s",
        len(pages),
        sum(len(p.visuals) for p in pages),
        report_dir,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marketplace_analytics", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="Path to settings.yaml")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download", help="Download and extract the Olist dataset")
    p.add_argument("--force", action="store_true", help="Re-download even if files exist")
    p.set_defaults(func=_download)

    p = sub.add_parser("build", help="Load raw CSVs, build SQL marts, run quality checks")
    p.set_defaults(func=_build)

    p = sub.add_parser("eda", help="Reconcile Python vs SQL metrics, run EDA, write charts")
    p.set_defaults(func=_eda)

    p = sub.add_parser("regression", help="Observational low-review regression (Olist)")
    p.set_defaults(func=_regression)

    p = sub.add_parser("experiment", help="SIMULATED checkout A/B experiment (sim schema)")
    p.add_argument("--replications", type=int, default=None, help="Override validation reps")
    p.set_defaults(func=_experiment)

    p = sub.add_parser(
        "experiment-regression", help="Logistic regression of the SIMULATED experiment"
    )
    p.add_argument("--replications", type=int, default=None, help="Override validation reps")
    p.set_defaults(func=_experiment_regression)

    p = sub.add_parser("export-powerbi", help="Export warehouse tables to Parquet for Power BI")
    p.set_defaults(func=_export_powerbi)

    p = sub.add_parser("powerbi-report", help="Generate the PBIR pages of the Power BI report")
    p.set_defaults(func=_powerbi_report)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        args.func(args)
    except (
        MissingRawDataError,
        DataQualityError,
        ReconciliationError,
        ExperimentReconciliationError,
        ExperimentRegressionError,
        PowerBIExportError,
    ) as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
