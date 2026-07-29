"""Command-line interface for downloading sources and building raw inputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from .sources import (
    SourceDataError,
    build_raw_data,
    download_sources,
    validate_sources,
)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download official AWM-cartel sources and build raw CSV inputs."
    )
    parser.add_argument(
        "command",
        choices=("download", "validate", "build", "all"),
        nargs="?",
        default="all",
        help="Operation to run (default: all).",
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
        help="Destination for the six normalized CSVs.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Download fresh copies even when a cached snapshot exists.",
    )
    parser.add_argument(
        "--municipality-source-id",
        default="statistik_austria_municipalities_2024",
        help=(
            "Registry source_id for the harmonized GKZ reference vintage "
            "(default: statistik_austria_municipalities_2024)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)

    try:
        if args.command in {"download", "all"}:
            summary = download_sources(args.sources_dir, refresh=args.refresh)
            print(
                f"Sources: {summary.downloaded} downloaded, "
                f"{summary.cached} reused; manifest: {summary.manifest_path}"
            )
        if args.command in {"validate", "build", "all"}:
            validation = validate_sources(args.sources_dir)
            print(
                f"Validation: {validation.verified_downloads} source snapshots "
                f"and {validation.curated_rows} curated rows verified."
            )
        if args.command in {"build", "all"}:
            summary = build_raw_data(
                args.sources_dir,
                args.raw_dir,
                municipality_source_id=args.municipality_source_id,
            )
            print(
                f"Raw inputs: {summary.municipalities} municipalities and "
                f"{summary.evidence_rows} evidence rows written to {summary.raw_dir}"
            )
    except SourceDataError as exc:
        parser.error(str(exc))
    return 0
