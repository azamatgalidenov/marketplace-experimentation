from __future__ import annotations

import zipfile

import pytest

from marketplace_analytics.data.download import (
    OLIST_FILES,
    MissingRawDataError,
    ensure_raw_data,
    extract_archive,
    missing_files,
)


def test_missing_files_reports_every_required_csv(tmp_path):
    missing = missing_files(tmp_path)
    assert "olist_orders_dataset.csv" in missing
    assert "olist_geolocation_dataset.csv" not in missing  # not required


def test_ensure_raw_data_gives_manual_instructions(tmp_path):
    with pytest.raises(MissingRawDataError, match="Manual download"):
        ensure_raw_data(tmp_path)


def test_extract_archive_only_extracts_known_members(tmp_path):
    zip_path = tmp_path / "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("nested/" + OLIST_FILES["orders"], "order_id\n1\n")
        archive.writestr("../evil.py", "print('x')")
    out = tmp_path / "raw"
    out.mkdir()
    extracted = extract_archive(zip_path, out)
    assert [p.name for p in extracted] == [OLIST_FILES["orders"]]
    assert not (tmp_path / "evil.py").exists()
