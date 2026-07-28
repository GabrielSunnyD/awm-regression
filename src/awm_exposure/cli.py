"""Command-line interface for the exposure builder."""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import InputError, build_exposure


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an ever-exposed AWM-cartel indicator by Austrian GKZ."
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
            include_data_found=not args.omit_data_found,
            write_audit=not args.no_audit,
        )
    except InputError as exc:
        parser.error(str(exc))

    print(
        f"Wrote {summary.municipalities} municipalities to "
        f"{summary.main_output} "
        f"({summary.exposed} exposed; {summary.with_data} with data)."
    )
    if summary.audit_output is not None:
        print(f"Wrote audit output to {summary.audit_output}.")
    return 0


