"""Command-line interface for the fixed-effects expenditure regression."""

from __future__ import annotations

import argparse
from pathlib import Path

from .regression import RegressionInputError, run_regression


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate expenditure on AWM-cartel exposure and time-varying "
            "controls with GKZ and year fixed effects."
        )
    )
    parser.add_argument(
        "--exposure-csv",
        type=Path,
        default=Path("data/processed/municipality_year_exposure.csv"),
        help=(
            "Long gkz,year,exposure,data_found panel "
            "(default: data/processed/municipality_year_exposure.csv)."
        ),
    )
    parser.add_argument(
        "--expenditure-csv",
        type=Path,
        required=True,
        help="Wide CSV with gkz plus one expenditure column per YYYY year.",
    )
    parser.add_argument(
        "--controls-csv",
        type=Path,
        help=(
            "Optional long CSV with gkz, year, and one numeric column per "
            "time-varying control."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/regression"),
        help="Directory for regression outputs (default: data/regression).",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        help="Optional first estimation year, inclusive.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        help="Optional last estimation year, inclusive.",
    )
    parser.add_argument(
        "--log-outcome",
        action="store_true",
        help="Estimate log(expenditure); all included expenditures must be positive.",
    )
    parser.add_argument(
        "--include-unknown-exposure",
        action="store_true",
        help=(
            "Treat data_found=false exposure rows as usable zeroes. This changes "
            "the default conservative exposure-coverage rule."
        ),
    )
    parser.add_argument(
        "--cluster",
        choices=("gkz", "gkz-year", "none"),
        default="gkz",
        help=(
            "Inference covariance: municipality-clustered (gkz, default), "
            "two-way clustered, or classical (none)."
        ),
    )
    parser.add_argument(
        "--confidence-level",
        type=float,
        default=0.95,
        help="Confidence-interval level between 0 and 1 (default: 0.95).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_regression(
            exposure_csv=args.exposure_csv,
            expenditure_csv=args.expenditure_csv,
            controls_csv=args.controls_csv,
            output_dir=args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            log_outcome=args.log_outcome,
            include_unknown_exposure=args.include_unknown_exposure,
            cluster=args.cluster,
            confidence_level=args.confidence_level,
        )
    except RegressionInputError as exc:
        parser.error(str(exc))

    print(
        f"Estimated {summary.observations} observations across "
        f"{summary.municipalities} GKZs and {summary.years} years."
    )
    print(
        f"Exposure coefficient: {summary.exposure_estimate:.6g} "
        f"(SE {summary.exposure_standard_error:.6g}); "
        f"within R-squared: {summary.within_r_squared:.4f}."
    )
    print(f"Results written to {summary.results_output}.")
    print(f"Estimation sample written to {summary.sample_output}.")
    print(f"Model metadata written to {summary.metadata_output}.")
    return 0
