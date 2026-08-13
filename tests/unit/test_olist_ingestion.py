"""Unit tests for public Olist dataset validation and provenance."""

import csv
import hashlib
from pathlib import Path

import pytest
from scripts.download_olist import (
    DEFAULT_OUTPUT_DIR,
    EXPECTED_FILES,
    build_manifest,
    locate_expected_files,
)
from scripts.load_olist import (
    DEFAULT_DATA_DIR,
    IMPORT_SPECS,
    normalize_psycopg_url,
    validate_headers,
)


def write_source_headers(data_dir: Path) -> None:
    for spec in IMPORT_SPECS:
        with (data_dir / spec.filename).open("w", encoding="utf-8", newline="") as target:
            csv.writer(target).writerow(spec.source_columns)


def test_loader_accepts_only_complete_exact_source_headers(tmp_path: Path) -> None:
    write_source_headers(tmp_path)

    paths = validate_headers(tmp_path)

    assert len(paths) == 9
    product_spec = next(spec for spec in IMPORT_SPECS if spec.table == "products")
    assert "product_name_lenght" in product_spec.source_columns
    assert "product_name_length" in product_spec.copy_columns


def test_loader_rejects_header_drift_before_database_access(tmp_path: Path) -> None:
    write_source_headers(tmp_path)
    (tmp_path / "olist_orders_dataset.csv").write_text(
        "order_id,unexpected_column\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unexpected header"):
        validate_headers(tmp_path)


def test_downloader_manifest_fingerprints_every_expected_file(tmp_path: Path) -> None:
    files: dict[str, Path] = {}
    for filename in EXPECTED_FILES:
        path = tmp_path / filename
        path.write_bytes(filename.encode())
        files[filename] = path

    located = locate_expected_files(tmp_path)
    manifest = build_manifest(located, tmp_path)

    assert len(manifest["files"]) == 9
    first = EXPECTED_FILES[0]
    assert manifest["files"][first]["sha256"] == hashlib.sha256(first.encode()).hexdigest()


def test_loader_accepts_sqlalchemy_psycopg_url() -> None:
    assert (
        normalize_psycopg_url("postgresql+psycopg://owner:secret@localhost/analytics")
        == "postgresql://owner:secret@localhost/analytics"
    )


def test_default_data_paths_are_independent_of_working_directory() -> None:
    assert DEFAULT_OUTPUT_DIR == DEFAULT_DATA_DIR
    assert DEFAULT_DATA_DIR.parts[-4:] == ("DataPilot", "data", "raw", "olist")
    assert DEFAULT_DATA_DIR.is_absolute()
