"""One-command acquisition, normalization, and panel build."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .pipeline import (
    DEFAULT_END_YEAR,
    DEFAULT_START_YEAR,
    InputError,
    build_exposure,
)
from .sources import (
    SourceDataError,
    build_raw_data,
    download_sources,
    validate_sources,
)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download official sources, normalize reviewed evidence, and build "
            "the long and wide municipality-year exposure outputs."
        )
    )
    parser.add_argument(
        "--sources-dir",
        type=Path,
        default=Path("data/sources"),
        help="Source registry, curated records, and downloads directory.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Destination for normalized source tables.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Destination for the long panel, wide matrix, and audit table.",
    )
    parser.add_argument(
        "--municipality-source-id",
        default="statistik_austria_municipalities_2024",
        help="Registry source_id for the harmonized GKZ reference vintage.",
    )
    parser.add_argument(
        "--municipality-changes-source-id",
        default="statistik_austria_admin_changes",
        help="Registry source_id for Statistics Austria's historical GKZ changes.",
    )
    parser.add_argument(
        "--municipality-reference-date",
        type=date.fromisoformat,
        default=date(2024, 1, 1),
        metavar="YYYY-MM-DD",
        help="Validity date of the municipality universe (default: 2024-01-01).",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
        help=f"First panel year, inclusive (default: {DEFAULT_START_YEAR}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
        help=f"Last panel year, inclusive (default: {DEFAULT_END_YEAR}).",
    )
    download_mode = parser.add_mutually_exclusive_group()
    download_mode.add_argument(
        "--refresh",
        action="store_true",
        help="Replace cached source snapshots before rebuilding.",
    )
    download_mode.add_argument(
        "--offline",
        action="store_true",
        help="Use existing source snapshots without making network requests.",
    )
    parser.add_argument(
        "--omit-data-found",
        action="store_true",
        help="Omit data_found from the simple panel output.",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Do not write the detailed municipality-year audit table.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)

    try:
        if not args.offline:
            downloads = download_sources(
                args.sources_dir,
                refresh=args.refresh,
            )
            print(
                f"Sources: {downloads.downloaded} downloaded, "
                f"{downloads.cached} reused; manifest: {downloads.manifest_path}"
            )

        validation = validate_sources(args.sources_dir)
        print(
            f"Validation: {validation.verified_downloads} source snapshots and "
            f"{validation.curated_rows} curated rows verified."
        )

        raw = build_raw_data(
            args.sources_dir,
            args.raw_dir,
            municipality_source_id=args.municipality_source_id,
            municipality_changes_source_id=args.municipality_changes_source_id,
            municipality_reference_date=args.municipality_reference_date,
        )
        print(
            f"Raw inputs: {raw.municipalities} municipalities and "
            f"{raw.crosswalk_rows} historical crosswalk rows; "
            f"{raw.evidence_rows} evidence rows written to {raw.raw_dir}"
        )

        panel = build_exposure(
            args.raw_dir,
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            include_data_found=not args.omit_data_found,
            write_audit=not args.no_audit,
        )
        print(
            f"Panel: {panel.rows} rows "
            f"({panel.municipalities} GKZ x {panel.years} years) written to "
            f"{panel.main_output}; {panel.exposed_rows} exposed rows and "
            f"{panel.with_data_rows} rows with data."
        )
        print(f"Wide exposure matrix written to {panel.wide_output}.")
    except (InputError, SourceDataError) as exc:
        parser.error(str(exc))
    return 0
