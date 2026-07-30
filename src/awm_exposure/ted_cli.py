"""CLI for generating a review-only TED procurement candidate queue."""

from __future__ import annotations

import argparse
from pathlib import Path

from .ted import TedDataError, download_ted_candidates


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find Austrian waste-procurement notices whose reported winner "
            "matches a reviewed cartel-participant alias. Output is a pending "
            "review queue and never changes exposure automatically."
        )
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=Path("data/sources/curated/participant_aliases.csv"),
        help="Source-backed participant alias table.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/review/procurement_candidates.csv"),
        help="Destination for the generated pending candidate queue.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2001,
        help="First TED publication year, inclusive (default: 2001).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2024,
        help="Last TED publication year, inclusive (default: 2024).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=250,
        help="TED results per request, maximum 250 (default: 250).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        summary = download_ted_candidates(
            args.aliases,
            args.output,
            start_year=args.start_year,
            end_year=args.end_year,
            page_size=args.page_size,
        )
    except TedDataError as exc:
        parser.error(str(exc))
    print(
        f"TED: examined {summary.notices_examined} notices across "
        f"{summary.pages} page(s); wrote {summary.candidates} pending "
        f"candidate(s) to {summary.output_path}"
    )
    return 0
