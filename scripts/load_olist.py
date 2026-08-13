"""Validate and atomically load the public Olist CSV files into PostgreSQL."""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import Connection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "raw" / "olist"


@dataclass(frozen=True)
class ImportSpec:
    filename: str
    table: str
    source_columns: tuple[str, ...]
    target_columns: tuple[str, ...] | None = None

    @property
    def copy_columns(self) -> tuple[str, ...]:
        return self.target_columns or self.source_columns


IMPORT_SPECS = (
    ImportSpec(
        "product_category_name_translation.csv",
        "product_category_translation",
        ("product_category_name", "product_category_name_english"),
    ),
    ImportSpec(
        "olist_customers_dataset.csv",
        "customers",
        (
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ),
    ),
    ImportSpec(
        "olist_geolocation_dataset.csv",
        "geolocation",
        (
            "geolocation_zip_code_prefix",
            "geolocation_lat",
            "geolocation_lng",
            "geolocation_city",
            "geolocation_state",
        ),
    ),
    ImportSpec(
        "olist_sellers_dataset.csv",
        "sellers",
        ("seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"),
    ),
    ImportSpec(
        "olist_products_dataset.csv",
        "products",
        (
            "product_id",
            "product_category_name",
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ),
        (
            "product_id",
            "product_category_name",
            "product_name_length",
            "product_description_length",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ),
    ),
    ImportSpec(
        "olist_orders_dataset.csv",
        "orders",
        (
            "order_id",
            "customer_id",
            "order_status",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ),
    ),
    ImportSpec(
        "olist_order_items_dataset.csv",
        "order_items",
        (
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ),
    ),
    ImportSpec(
        "olist_order_payments_dataset.csv",
        "order_payments",
        (
            "order_id",
            "payment_sequential",
            "payment_type",
            "payment_installments",
            "payment_value",
        ),
    ),
    ImportSpec(
        "olist_order_reviews_dataset.csv",
        "order_reviews",
        (
            "review_id",
            "order_id",
            "review_score",
            "review_comment_title",
            "review_comment_message",
            "review_creation_date",
            "review_answer_timestamp",
        ),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load validated Olist CSVs into an initialized DataPilot PostgreSQL database."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Directory containing the nine Olist CSV files (default: {DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--database-url",
        help="PostgreSQL owner/writer URL. Defaults to DATAPILOT_DATA_LOADER_DATABASE_URL.",
    )
    return parser.parse_args()


def find_csv(data_dir: Path, filename: str) -> Path:
    matches = sorted(data_dir.rglob(filename))
    if not matches:
        raise FileNotFoundError(f"Missing required Olist file: {filename}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple copies of {filename} found under {data_dir}")
    return matches[0]


def validate_headers(data_dir: Path) -> dict[ImportSpec, Path]:
    paths: dict[ImportSpec, Path] = {}
    for spec in IMPORT_SPECS:
        path = find_csv(data_dir, spec.filename)
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            actual = tuple(next(csv.reader(source), ()))
        if actual != spec.source_columns:
            raise ValueError(
                f"Unexpected header in {spec.filename}. "
                f"Expected {spec.source_columns!r}, got {actual!r}"
            )
        paths[spec] = path
    return paths


def normalize_psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def verify_schema(connection: Connection[object]) -> None:
    expected = {spec.table for spec in IMPORT_SPECS}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'olist' AND table_type = 'BASE TABLE'
            """
        )
        actual = {row[0] for row in cursor.fetchall()}
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(
            "The Olist schema is not initialized; missing tables: " + ", ".join(missing)
        )


def truncate_olist(connection: Connection[object]) -> None:
    tables = ", ".join(f"olist.{spec.table}" for spec in reversed(IMPORT_SPECS))
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {tables}")


def copy_csv(connection: Connection[object], spec: ImportSpec, path: Path) -> None:
    columns = ", ".join(spec.copy_columns)
    statement = (
        f"COPY olist.{spec.table} ({columns}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, NULL '')"
    )
    with (
        connection.cursor() as cursor,
        cursor.copy(statement) as copy,
        path.open("rb") as source,
    ):
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            copy.write(chunk)


def table_counts(connection: Connection[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for spec in IMPORT_SPECS:
            cursor.execute(f"SELECT COUNT(*) FROM olist.{spec.table}")
            counts[spec.table] = int(cursor.fetchone()[0])
    return counts


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    paths = validate_headers(data_dir)
    database_url = args.database_url or os.getenv("DATAPILOT_DATA_LOADER_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "Set DATAPILOT_DATA_LOADER_DATABASE_URL to an owner/writer PostgreSQL URL "
            "or pass --database-url."
        )

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            'Psycopg is required. Install it with: python -m pip install -e ".[postgres]"'
        ) from exc

    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        verify_schema(connection)
        truncate_olist(connection)
        for spec in IMPORT_SPECS:
            copy_csv(connection, spec, paths[spec])
        counts = table_counts(connection)

    print("Olist import committed successfully:")
    for table, count in counts.items():
        print(f"  olist.{table}: {count:,} rows")


if __name__ == "__main__":
    main()
