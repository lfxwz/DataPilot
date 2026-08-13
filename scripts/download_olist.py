"""Download and verify the public Olist dataset without committing raw data."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATASET_HANDLE = "olistbr/brazilian-ecommerce"
DATASET_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "olist"
EXPECTED_FILES = (
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download the original Olist Brazilian e-commerce CSV files from Kaggle."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Local destination for untracked raw files (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ask KaggleHub to download the dataset again.",
    )
    return parser.parse_args()


def locate_expected_files(root: Path) -> dict[str, Path]:
    located: dict[str, Path] = {}
    for filename in EXPECTED_FILES:
        matches = sorted(root.rglob(filename))
        if not matches:
            raise FileNotFoundError(f"Dataset is incomplete: missing {filename} under {root}")
        if len(matches) > 1:
            paths = ", ".join(str(path) for path in matches)
            raise RuntimeError(f"Dataset contains multiple copies of {filename}: {paths}")
        located[filename] = matches[0]
    return located


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(files: dict[str, Path], root: Path) -> dict[str, Any]:
    return {
        "dataset_handle": DATASET_HANDLE,
        "source_url": DATASET_URL,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "files": {
            filename: {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for filename, path in sorted(files.items())
        },
    }


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import kagglehub
    except ImportError as exc:
        raise SystemExit(
            'KaggleHub is required. Install it with: python -m pip install -e ".[data]"'
        ) from exc

    downloaded_path = Path(
        kagglehub.dataset_download(
            DATASET_HANDLE,
            output_dir=str(output_dir),
            force_download=args.force,
        )
    )
    search_root = downloaded_path if downloaded_path.exists() else output_dir
    files = locate_expected_files(search_root)
    manifest = build_manifest(files, search_root)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Verified {len(files)} Olist CSV files in {search_root}")
    print(f"Wrote integrity manifest to {manifest_path}")


if __name__ == "__main__":
    main()
