"""Download and extract the Olist Brazilian E-Commerce dataset."""

from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Logical table name -> CSV file name inside the Kaggle archive.
OLIST_FILES: dict[str, str] = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

# Tables the warehouse needs. Geolocation is large and not used by the analyses.
REQUIRED_TABLES = [name for name in OLIST_FILES if name != "geolocation"]

MANUAL_INSTRUCTIONS = """\
Manual download:
  1. Open https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce and sign in.
  2. Click "Download" to get the zip archive.
  3. Put the CSV files (or the zip) into {raw_dir}.
  4. Run:  uv run python -m marketplace_analytics build
"""


class MissingRawDataError(FileNotFoundError):
    """Raised when required Olist CSV files are not present."""


def missing_files(raw_dir: Path, tables: list[str] | None = None) -> list[str]:
    tables = tables or REQUIRED_TABLES
    return [OLIST_FILES[t] for t in tables if not (raw_dir / OLIST_FILES[t]).exists()]


def ensure_raw_data(raw_dir: Path) -> None:
    """Raise a helpful error if the CSVs needed by the warehouse are missing."""
    missing = missing_files(raw_dir)
    if missing:
        raise MissingRawDataError(
            f"Missing Olist files in {raw_dir}: {', '.join(missing)}\n"
            + MANUAL_INSTRUCTIONS.format(raw_dir=raw_dir)
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_archive(zip_path: Path, raw_dir: Path) -> list[Path]:
    """Extract only the known CSV members, refusing anything unexpected."""
    extracted = []
    with zipfile.ZipFile(zip_path) as archive:
        members = {Path(name).name: name for name in archive.namelist()}
        for file_name in OLIST_FILES.values():
            if file_name not in members:
                logger.warning("Archive does not contain %s", file_name)
                continue
            target = raw_dir / file_name
            with archive.open(members[file_name]) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target)
    logger.info("Extracted %d files to %s", len(extracted), raw_dir)
    return extracted


def download_olist(
    raw_dir: Path, url: str, expected_sha256: str | None = None, force: bool = False
) -> Path:
    """Download the Olist archive into ``raw_dir`` and extract the CSV files."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    if not force and not missing_files(raw_dir):
        logger.info("All Olist CSV files already present in %s; skipping download", raw_dir)
        return raw_dir

    zip_path = raw_dir / "brazilian-ecommerce.zip"
    if force or not zip_path.exists():
        logger.info("Downloading Olist dataset from %s", url)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "marketplace-analytics"})
            with (
                urllib.request.urlopen(request, timeout=300) as response,
                open(zip_path, "wb") as out,
            ):
                shutil.copyfileobj(response, out)
        except OSError as exc:
            zip_path.unlink(missing_ok=True)
            raise MissingRawDataError(
                f"Automatic download failed ({exc}).\n"
                + MANUAL_INSTRUCTIONS.format(raw_dir=raw_dir)
            ) from exc

    digest = sha256(zip_path)
    if expected_sha256 and digest != expected_sha256:
        logger.warning(
            "Archive SHA-256 %s differs from the documented %s. Kaggle may have "
            "repackaged it; the data-quality checks will reveal content changes.",
            digest,
            expected_sha256,
        )
    else:
        logger.info("Archive SHA-256 verified: %s", digest)

    extract_archive(zip_path, raw_dir)
    ensure_raw_data(raw_dir)
    return raw_dir
