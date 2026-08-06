"""Command-line interface for the municipality-year exposure builder."""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import (
    DEFAULT_END_YEAR,
    DEFAULT_START_YEAR,
    InputError,
    build_exposure,
)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build long and wide dated AWM-cartel exposure outputs for every "
            "Austrian GKZ-year."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory containing the input CSV files (default: data/raw).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory for generated CSV files (default: data/processed).",
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
    parser.add_argument(
        "--omit-data-found",
        action="store_true",
        help="Omit data_found from the main output.",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Do not write the detailed audit output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)

    try:
        summary = build_exposure(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            include_data_found=not args.omit_data_found,
            write_audit=not args.no_audit,
        )
    except InputError as exc:
        parser.error(str(exc))

    print(
        f"Wrote {summary.rows} rows "
        f"({summary.municipalities} GKZ x {summary.years} years) to "
        f"{summary.main_output}; {summary.exposed_rows} exposed rows across "
        f"{summary.ever_exposed_municipalities} municipalities and "
        f"{summary.with_data_rows} rows with data."
    )
    print(f"Wrote wide exposure output to {summary.wide_output}.")
    if summary.audit_output is not None:
        print(f"Wrote audit output to {summary.audit_output}.")
    return 0
