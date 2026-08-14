"""Estimate expenditure effects with municipality and year fixed effects.

The analysis layer is deliberately explicit about data transformations.  It
joins the project's long exposure panel to a single long regression-input CSV,
applies complete-case filtering, residualizes all model variables against GKZ
and year fixed effects, and estimates OLS with cluster-aware inference.  It
does not deflate, winsorize, log, or otherwise transform researcher-supplied
variables unless the caller requests the documented log-outcome option.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
from scipy import stats


class RegressionInputError(ValueError):
    """Raised when regression inputs or the resulting model are not valid."""


@dataclass(frozen=True)
class RegressionSummary:
    """Key model statistics and paths written by :func:`run_regression`."""

    observations: int
    municipalities: int
    years: int
    controls: tuple[str, ...]
    exposed_observations: int
    within_r_squared: float
    exposure_estimate: float
    exposure_standard_error: float
    results_output: Path
    sample_output: Path
    metadata_output: Path
    text_output: Path


@dataclass(frozen=True)
class _ExposureValue:
    exposure: float
    data_found: bool | None


@dataclass(frozen=True)
class _AnalysisValue:
    expenditure: float | None
    controls: tuple[float | None, ...]


@dataclass(frozen=True)
class _Observation:
    gkz: str
    year: int
    exposure: float
    data_found: bool | None
    expenditure: float
    controls: tuple[float, ...]


_GKZ = re.compile(r"^\d{5}$")
_YEAR = re.compile(r"^\d{4}$")
_MISSING_VALUES = {"", ".", "na", "n/a", "nan", "null"}
_CLUSTER_OPTIONS = {"gkz", "gkz-year", "none"}
_EXPOSURE_COLUMNS = {"exposure", "exposure_direct", "exposure_regional"}
_RESERVED_CONTROL_NAMES = {
    "gkz",
    "year",
    "exposure",
    "data_found",
    "expenditure",
    "model_outcome",
    "within_outcome",
    "within_fitted",
    "residual",
}


def _normalize_gkz(value: str, context: str) -> str:
    cleaned = value.strip()
    if cleaned.isdigit() and 1 <= len(cleaned) <= 5:
        cleaned = cleaned.zfill(5)
    if not _GKZ.fullmatch(cleaned):
        raise RegressionInputError(
            f"{context}: GKZ must contain one to five digits: {value!r}"
        )
    return cleaned


def _parse_year(value: str, context: str) -> int:
    cleaned = value.strip()
    if not _YEAR.fullmatch(cleaned):
        raise RegressionInputError(f"{context}: year must use YYYY: {value!r}")
    year = int(cleaned)
    if not 1 <= year <= 9999:
        raise RegressionInputError(f"{context}: year is out of range: {year}")
    return year


def _parse_bool(value: str, context: str) -> bool:
    cleaned = value.strip().lower()
    if cleaned in {"1", "true", "yes", "y"}:
        return True
    if cleaned in {"0", "false", "no", "n"}:
        return False
    raise RegressionInputError(
        f"{context}: expected a boolean (0/1 or true/false), got {value!r}"
    )


def _parse_number(value: str, context: str, *, optional: bool) -> float | None:
    cleaned = value.strip()
    if cleaned.lower() in _MISSING_VALUES:
        if optional:
            return None
        raise RegressionInputError(f"{context}: value cannot be missing")
    try:
        number = float(cleaned)
    except ValueError as exc:
        raise RegressionInputError(
            f"{context}: expected a numeric value, got {value!r}"
        ) from exc
    if not math.isfinite(number):
        raise RegressionInputError(f"{context}: numeric values must be finite")
    return number


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise RegressionInputError(f"Required input is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RegressionInputError(f"{path} has no header row")
        original_fields = list(reader.fieldnames)
        fields = [field.strip() for field in original_fields]
        if any(not field for field in fields):
            raise RegressionInputError(f"{path} contains a blank column name")
        duplicates = sorted(
            field for field, count in Counter(fields).items() if count > 1
        )
        if duplicates:
            raise RegressionInputError(
                f"{path} contains duplicate column(s): {', '.join(duplicates)}"
            )
        rename = dict(zip(original_fields, fields, strict=True))
        rows: list[dict[str, str]] = []
        for line_number, raw in enumerate(reader, start=2):
            overflow = raw.get(None)
            if isinstance(overflow, list) and any(
                (value or "").strip() for value in overflow
            ):
                raise RegressionInputError(
                    f"{path}:{line_number}: row has more cells than the header"
                )
            row = {
                rename[key]: (value or "").strip()
                for key, value in raw.items()
                if key is not None
            }
            if not any(row.values()):
                continue
            row["_line"] = str(line_number)
            rows.append(row)
        return fields, rows


def _context(path: Path, row: Mapping[str, str]) -> str:
    return f"{path}:{row.get('_line', '?')}"


def _require_columns(path: Path, fields: Sequence[str], required: set[str]) -> None:
    missing = required - set(fields)
    if missing:
        raise RegressionInputError(
            f"{path} is missing required column(s): {', '.join(sorted(missing))}"
        )


def _read_exposure(
    path: Path,
    *,
    exposure_column: str = "exposure",
) -> tuple[dict[tuple[str, int], _ExposureValue], bool]:
    fields, rows = _read_rows(path)
    if exposure_column not in _EXPOSURE_COLUMNS:
        raise RegressionInputError(
            "exposure_column must be exposure, exposure_direct, or "
            "exposure_regional"
        )
    _require_columns(path, fields, {"gkz", "year", exposure_column})
    has_data_found = "data_found" in fields
    allowed = {
        "gkz", "year", "exposure", "exposure_direct", "exposure_regional",
        "exposure_basis", "data_found", "data_found_direct",
        "data_found_regional",
    }
    unexpected = sorted(set(fields) - allowed)
    if unexpected:
        raise RegressionInputError(
            f"{path} contains unexpected column(s): {', '.join(unexpected)}"
        )

    values: dict[tuple[str, int], _ExposureValue] = {}
    for row in rows:
        context = _context(path, row)
        key = (
            _normalize_gkz(row["gkz"], context),
            _parse_year(row["year"], context),
        )
        if key in values:
            raise RegressionInputError(
                f"{context}: duplicate exposure row for GKZ {key[0]}, year {key[1]}"
            )
        exposure = _parse_number(row[exposure_column], context, optional=False)
        assert exposure is not None
        if exposure not in {0.0, 1.0}:
            raise RegressionInputError(
                f"{context}: exposure must be binary (0 or 1), got {exposure}"
            )
        if {"exposure", "exposure_direct", "exposure_regional"}.issubset(fields):
            combined = _parse_number(row["exposure"], context, optional=False)
            direct = _parse_number(row["exposure_direct"], context, optional=False)
            regional = _parse_number(
                row["exposure_regional"], context, optional=False
            )
            if any(value not in {0.0, 1.0} for value in (combined, direct, regional)):
                raise RegressionInputError(
                    f"{context}: all exposure columns must be binary"
                )
            if combined != max(direct, regional):
                raise RegressionInputError(
                    f"{context}: exposure must equal max(exposure_direct, "
                    "exposure_regional)"
                )
        selected_data_found = {
            "exposure": "data_found",
            "exposure_direct": "data_found_direct",
            "exposure_regional": "data_found_regional",
        }[exposure_column]
        if selected_data_found not in fields:
            selected_data_found = "data_found"
        data_found = (
            _parse_bool(row[selected_data_found], context)
            if selected_data_found in fields
            else None
        )
        if exposure == 1.0 and data_found is False:
            raise RegressionInputError(
                f"{context}: exposure=1 cannot have data_found=false"
            )
        values[key] = _ExposureValue(exposure, data_found)
    if not values:
        raise RegressionInputError(f"{path} contains no exposure rows")
    return values, has_data_found


def _read_analysis_input(
    path: Path,
) -> tuple[tuple[str, ...], dict[tuple[str, int], _AnalysisValue]]:
    fields, rows = _read_rows(path)
    _require_columns(path, fields, {"gkz", "year", "expenditure"})
    control_names = tuple(
        field for field in fields if field not in {"gkz", "year", "expenditure"}
    )
    reserved = sorted(
        name for name in control_names if name.lower() in _RESERVED_CONTROL_NAMES
    )
    if reserved:
        raise RegressionInputError(
            f"{path} uses reserved control name(s): {', '.join(reserved)}"
        )

    values: dict[tuple[str, int], _AnalysisValue] = {}
    for row in rows:
        context = _context(path, row)
        key = (
            _normalize_gkz(row["gkz"], context),
            _parse_year(row["year"], context),
        )
        if key in values:
            raise RegressionInputError(
                f"{context}: duplicate input row for GKZ {key[0]}, year {key[1]}"
            )
        values[key] = _AnalysisValue(
            expenditure=_parse_number(
                row["expenditure"],
                f"{context} column expenditure",
                optional=True,
            ),
            controls=tuple(
                _parse_number(row[name], f"{context} column {name}", optional=True)
                for name in control_names
            ),
        )
    if not values:
        raise RegressionInputError(f"{path} contains no input rows")
    return control_names, values


def _drop_singletons(
    observations: list[_Observation],
) -> tuple[list[_Observation], int, int]:
    """Iteratively remove GKZ or year groups represented by one observation."""

    kept = observations
    dropped = 0
    iterations = 0
    while kept:
        gkz_counts = Counter(row.gkz for row in kept)
        year_counts = Counter(row.year for row in kept)
        filtered = [
            row
            for row in kept
            if gkz_counts[row.gkz] > 1 and year_counts[row.year] > 1
        ]
        removed = len(kept) - len(filtered)
        if removed == 0:
            return kept, dropped, iterations
        kept = filtered
        dropped += removed
        iterations += 1
    return kept, dropped, iterations


def _factorize(values: Sequence[str | int]) -> tuple[np.ndarray, tuple[str | int, ...]]:
    levels = tuple(sorted(set(values)))
    lookup = {value: index for index, value in enumerate(levels)}
    codes = np.fromiter((lookup[value] for value in values), dtype=np.int64)
    return codes, levels


def _demean_once(
    values: np.ndarray, codes: np.ndarray, group_count: int
) -> np.ndarray:
    sums = np.zeros((group_count, values.shape[1]), dtype=np.float64)
    np.add.at(sums, codes, values)
    counts = np.bincount(codes, minlength=group_count).astype(np.float64)
    return values - (sums / counts[:, None])[codes]


def _residualize_two_way(
    values: np.ndarray,
    gkz_codes: np.ndarray,
    year_codes: np.ndarray,
    gkz_count: int,
    year_count: int,
    *,
    tolerance: float = 1e-12,
    max_iterations: int = 10_000,
) -> tuple[np.ndarray, int]:
    residualized = values.astype(np.float64, copy=True)
    for iteration in range(1, max_iterations + 1):
        previous = residualized.copy()
        residualized = _demean_once(residualized, gkz_codes, gkz_count)
        residualized = _demean_once(residualized, year_codes, year_count)
        delta = float(np.max(np.abs(residualized - previous)))
        scale = max(1.0, float(np.max(np.abs(residualized))))
        if delta <= tolerance * scale:
            return residualized, iteration
    raise RegressionInputError(
        "GKZ/year fixed-effect residualization did not converge; inspect the "
        "sample structure or rescale unusually large variables"
    )


def _fixed_effect_rank(
    gkz_codes: np.ndarray,
    year_codes: np.ndarray,
    gkz_count: int,
    year_count: int,
) -> tuple[int, int]:
    """Return dummy-matrix rank and connected components of the FE graph."""

    parent = list(range(gkz_count + year_count))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for gkz_code, year_code in zip(gkz_codes, year_codes, strict=True):
        union(int(gkz_code), gkz_count + int(year_code))
    components = len(
        {
            find(node)
            for node in range(gkz_count + year_count)
        }
    )
    return gkz_count + year_count - components, components


def _cluster_covariance_component(
    x: np.ndarray,
    residuals: np.ndarray,
    bread: np.ndarray,
    codes: np.ndarray,
    cluster_count: int,
    residual_df: int,
) -> np.ndarray:
    if cluster_count <= 1:
        raise RegressionInputError(
            "Clustered inference requires at least two clusters"
        )
    scores = np.zeros((cluster_count, x.shape[1]), dtype=np.float64)
    np.add.at(scores, codes, x * residuals[:, None])
    meat = scores.T @ scores
    correction = (cluster_count / (cluster_count - 1)) * (
        (len(x) - 1) / residual_df
    )
    return correction * (bread @ meat @ bread)


def _format_number(value: float) -> str:
    if math.isnan(value):
        return ""
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return f"{value:.12g}"


def _write_csv_atomic(
    path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _validate_options(
    *,
    start_year: int | None,
    end_year: int | None,
    cluster: str,
    confidence_level: float,
) -> None:
    if start_year is not None and not 1 <= start_year <= 9999:
        raise RegressionInputError("start_year must be between 1 and 9999")
    if end_year is not None and not 1 <= end_year <= 9999:
        raise RegressionInputError("end_year must be between 1 and 9999")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise RegressionInputError("start_year cannot be after end_year")
    if cluster not in _CLUSTER_OPTIONS:
        raise RegressionInputError(
            f"cluster must be one of {', '.join(sorted(_CLUSTER_OPTIONS))}"
        )
    if not 0.0 < confidence_level < 1.0:
        raise RegressionInputError("confidence_level must be between 0 and 1")


def run_regression(
    exposure_csv: Path | str,
    input_csv: Path | str,
    output_dir: Path | str,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    log_outcome: bool = False,
    include_unknown_exposure: bool = False,
    cluster: str = "gkz",
    confidence_level: float = 0.95,
    exposure_column: str = "exposure",
) -> RegressionSummary:
    """Join inputs and estimate expenditure on exposure, controls, and FE.

    The model always includes GKZ and year fixed effects.  Rows with
    ``data_found=false`` are excluded by default because the exposure pipeline
    defines them as unknown coverage rather than verified non-exposure.
    """

    _validate_options(
        start_year=start_year,
        end_year=end_year,
        cluster=cluster,
        confidence_level=confidence_level,
    )
    exposure_path = Path(exposure_csv)
    input_path = Path(input_csv)
    destination = Path(output_dir)

    exposure_values, has_data_found = _read_exposure(
        exposure_path, exposure_column=exposure_column
    )
    if not has_data_found and not include_unknown_exposure:
        raise RegressionInputError(
            f"{exposure_path} has no data_found column. Rebuild the standard long "
            "exposure panel or explicitly pass include_unknown_exposure=True."
        )
    control_names, analysis_values = _read_analysis_input(input_path)

    diagnostics = {
        "exposure_rows": len(exposure_values),
        "input_rows": len(analysis_values),
        "outside_requested_years": 0,
        "unknown_exposure": 0,
        "missing_input_row": 0,
        "missing_expenditure": 0,
        "missing_controls": 0,
        "singleton_fixed_effect": 0,
    }
    observations: list[_Observation] = []
    for (gkz, year), exposure_value in sorted(exposure_values.items()):
        if start_year is not None and year < start_year:
            diagnostics["outside_requested_years"] += 1
            continue
        if end_year is not None and year > end_year:
            diagnostics["outside_requested_years"] += 1
            continue
        if not include_unknown_exposure and exposure_value.data_found is not True:
            diagnostics["unknown_exposure"] += 1
            continue

        analysis_value = analysis_values.get((gkz, year))
        if analysis_value is None:
            diagnostics["missing_input_row"] += 1
            continue
        expenditure = analysis_value.expenditure
        if expenditure is None:
            diagnostics["missing_expenditure"] += 1
            continue
        if log_outcome and expenditure <= 0:
            raise RegressionInputError(
                "--log-outcome requires strictly positive expenditure; "
                f"found {expenditure} for GKZ {gkz}, year {year}"
            )

        raw_controls = analysis_value.controls
        if any(value is None for value in raw_controls):
            diagnostics["missing_controls"] += 1
            continue
        controls = tuple(float(value) for value in raw_controls if value is not None)
        observations.append(
            _Observation(
                gkz=gkz,
                year=year,
                exposure=exposure_value.exposure,
                data_found=exposure_value.data_found,
                expenditure=expenditure,
                controls=controls,
            )
        )

    observations, singleton_rows, singleton_iterations = _drop_singletons(
        observations
    )
    diagnostics["singleton_fixed_effect"] = singleton_rows
    if not observations:
        raise RegressionInputError(
            "No estimable observations remain after coverage, complete-case, and "
            "fixed-effect singleton filtering"
        )

    gkz_codes, gkz_levels = _factorize([row.gkz for row in observations])
    year_codes, year_levels = _factorize([row.year for row in observations])
    if len(gkz_levels) < 2 or len(year_levels) < 2:
        raise RegressionInputError(
            "Two-way fixed effects require at least two GKZs and two years"
        )

    raw_outcome = np.asarray(
        [row.expenditure for row in observations], dtype=np.float64
    )
    outcome = np.log(raw_outcome) if log_outcome else raw_outcome.copy()
    features = np.asarray(
        [
            (row.exposure, *row.controls)
            for row in observations
        ],
        dtype=np.float64,
    )
    combined = np.column_stack((outcome, features))
    within, fe_iterations = _residualize_two_way(
        combined,
        gkz_codes,
        year_codes,
        len(gkz_levels),
        len(year_levels),
    )
    within_outcome = within[:, 0]
    within_features = within[:, 1:]

    singular_values = np.linalg.svd(within_features, compute_uv=False)
    largest = float(singular_values[0]) if len(singular_values) else 0.0
    rank_tolerance = (
        max(within_features.shape) * np.finfo(np.float64).eps * largest
    )
    feature_rank = int(np.sum(singular_values > rank_tolerance))
    feature_names = ("exposure", *control_names)
    if feature_rank < len(feature_names):
        raise RegressionInputError(
            "Exposure and controls are rank deficient after GKZ/year fixed "
            "effects. Remove constants, duplicate controls, or variables with "
            "no within-GKZ variation."
        )
    within_total = float(within_outcome @ within_outcome)
    if within_total <= np.finfo(np.float64).eps * max(1.0, float(outcome @ outcome)):
        raise RegressionInputError(
            "Expenditure has no variation remaining after GKZ/year fixed effects"
        )

    fe_rank, fe_components = _fixed_effect_rank(
        gkz_codes,
        year_codes,
        len(gkz_levels),
        len(year_levels),
    )
    effective_parameters = fe_rank + feature_rank
    residual_df = len(observations) - effective_parameters
    if residual_df <= 0:
        raise RegressionInputError(
            "The complete-case sample has no residual degrees of freedom after "
            "fixed effects and regressors"
        )

    try:
        coefficients, _, _, _ = np.linalg.lstsq(
            within_features, within_outcome, rcond=None
        )
    except np.linalg.LinAlgError as exc:
        raise RegressionInputError(
            "The fixed-effects least-squares solver did not converge; inspect "
            "variable scaling and collinearity"
        ) from exc
    fitted_within = within_features @ coefficients
    residuals = within_outcome - fitted_within
    residual_sum_squares = float(residuals @ residuals)
    within_r_squared = 1.0 - residual_sum_squares / within_total
    xtx = within_features.T @ within_features
    try:
        bread = np.linalg.inv(xtx)
    except np.linalg.LinAlgError as exc:
        raise RegressionInputError(
            "The within-transformed design matrix is numerically singular; "
            "inspect variable scaling and collinearity"
        ) from exc

    if cluster == "none":
        covariance = (residual_sum_squares / residual_df) * bread
        inference_df = residual_df
        cluster_counts: dict[str, int] = {}
    elif cluster == "gkz":
        covariance = _cluster_covariance_component(
            within_features,
            residuals,
            bread,
            gkz_codes,
            len(gkz_levels),
            residual_df,
        )
        inference_df = len(gkz_levels) - 1
        cluster_counts = {"gkz": len(gkz_levels)}
    else:
        pair_codes = np.arange(len(observations), dtype=np.int64)
        covariance = (
            _cluster_covariance_component(
                within_features,
                residuals,
                bread,
                gkz_codes,
                len(gkz_levels),
                residual_df,
            )
            + _cluster_covariance_component(
                within_features,
                residuals,
                bread,
                year_codes,
                len(year_levels),
                residual_df,
            )
            - _cluster_covariance_component(
                within_features,
                residuals,
                bread,
                pair_codes,
                len(observations),
                residual_df,
            )
        )
        inference_df = min(len(gkz_levels), len(year_levels)) - 1
        cluster_counts = {
            "gkz": len(gkz_levels),
            "year": len(year_levels),
        }

    variances = np.diag(covariance).copy()
    negative_tolerance = 1e-10 * max(
        1.0, float(np.max(np.abs(variances)))
    )
    if np.any(variances < -negative_tolerance):
        raise RegressionInputError(
            "The requested clustered covariance produced a negative coefficient "
            "variance. Use more clusters or a different documented inference option."
        )
    standard_errors = np.sqrt(np.maximum(variances, 0.0))
    critical_value = float(
        stats.t.ppf((1.0 + confidence_level) / 2.0, inference_df)
    )

    result_rows: list[dict[str, object]] = []
    for index, name in enumerate(feature_names):
        estimate = float(coefficients[index])
        standard_error = float(standard_errors[index])
        if standard_error == 0.0:
            t_statistic = math.copysign(math.inf, estimate) if estimate else math.nan
        else:
            t_statistic = estimate / standard_error
        p_value = (
            float(2.0 * stats.t.sf(abs(t_statistic), inference_df))
            if not math.isnan(t_statistic)
            else math.nan
        )
        result_rows.append(
            {
                "term": name,
                "estimate": _format_number(estimate),
                "std_error": _format_number(standard_error),
                "t_statistic": _format_number(t_statistic),
                "p_value": _format_number(p_value),
                "ci_lower": _format_number(estimate - critical_value * standard_error),
                "ci_upper": _format_number(estimate + critical_value * standard_error),
            }
        )

    results_output = destination / "regression_results.csv"
    sample_output = destination / "regression_sample.csv"
    metadata_output = destination / "regression_metadata.json"
    text_output = destination / "regression_summary.txt"
    _write_csv_atomic(
        results_output,
        [
            "term",
            "estimate",
            "std_error",
            "t_statistic",
            "p_value",
            "ci_lower",
            "ci_upper",
        ],
        result_rows,
    )

    sample_rows: list[dict[str, object]] = []
    for index, row in enumerate(observations):
        sample_row: dict[str, object] = {
            "gkz": row.gkz,
            "year": row.year,
            "exposure": int(row.exposure),
            "data_found": (
                "" if row.data_found is None else str(row.data_found).lower()
            ),
            "expenditure": _format_number(row.expenditure),
        }
        sample_row.update(
            {
                name: _format_number(value)
                for name, value in zip(control_names, row.controls, strict=True)
            }
        )
        sample_row.update(
            {
                "model_outcome": _format_number(float(outcome[index])),
                "within_outcome": _format_number(float(within_outcome[index])),
                "within_fitted": _format_number(float(fitted_within[index])),
                "residual": _format_number(float(residuals[index])),
            }
        )
        sample_rows.append(sample_row)
    _write_csv_atomic(
        sample_output,
        [
            "gkz",
            "year",
            "exposure",
            "data_found",
            "expenditure",
            *control_names,
            "model_outcome",
            "within_outcome",
            "within_fitted",
            "residual",
        ],
        sample_rows,
    )

    outcome_label = "log(expenditure)" if log_outcome else "expenditure"
    formula = (
        f"{outcome_label} ~ exposure"
        + (" + " + " + ".join(control_names) if control_names else "")
        + " | gkz + year"
    )
    metadata = {
        "schema_version": 2,
        "model": {
            "formula": formula,
            "outcome": outcome_label,
            "controls": list(control_names),
            "fixed_effects": ["gkz", "year"],
            "standard_errors": cluster,
            "confidence_level": confidence_level,
            "include_unknown_exposure": include_unknown_exposure,
        },
        "inputs": {
            "exposure_csv": str(exposure_path),
            "input_csv": str(input_path),
            "start_year": start_year,
            "end_year": end_year,
        },
        "sample": {
            "observations": len(observations),
            "municipalities": len(gkz_levels),
            "years": len(year_levels),
            "first_year": min(int(year) for year in year_levels),
            "last_year": max(int(year) for year in year_levels),
            "exposed_observations": sum(
                row.exposure == 1.0 for row in observations
            ),
            "drop_counts": diagnostics,
            "singleton_pruning_iterations": singleton_iterations,
        },
        "estimation": {
            "within_r_squared": within_r_squared,
            "residual_sum_squares": residual_sum_squares,
            "feature_rank": feature_rank,
            "fixed_effect_rank": fe_rank,
            "fixed_effect_components": fe_components,
            "effective_parameters": effective_parameters,
            "residual_degrees_of_freedom": residual_df,
            "inference_degrees_of_freedom": inference_df,
            "cluster_counts": cluster_counts,
            "fixed_effect_iterations": fe_iterations,
            "condition_number": (
                float(singular_values[0] / singular_values[-1])
                if singular_values[-1] > 0
                else math.inf
            ),
        },
        "outputs": {
            "results_csv": str(results_output),
            "sample_csv": str(sample_output),
            "metadata_json": str(metadata_output),
            "summary_txt": str(text_output),
        },
    }
    _write_text_atomic(
        metadata_output,
        json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )

    heading = "Two-way fixed-effects OLS\n"
    lines = [
        heading,
        f"Formula: {formula}\n",
        f"Observations: {len(observations)}\n",
        f"Municipalities: {len(gkz_levels)}\n",
        f"Years: {len(year_levels)}\n",
        f"Standard errors: {cluster}\n",
        f"Within R-squared: {within_r_squared:.6f}\n",
        "\n",
        "term, estimate, std_error, t_statistic, p_value\n",
    ]
    lines.extend(
        f"{row['term']}, {row['estimate']}, {row['std_error']}, "
        f"{row['t_statistic']}, {row['p_value']}\n"
        for row in result_rows
    )
    _write_text_atomic(text_output, "".join(lines))

    return RegressionSummary(
        observations=len(observations),
        municipalities=len(gkz_levels),
        years=len(year_levels),
        controls=control_names,
        exposed_observations=sum(row.exposure == 1.0 for row in observations),
        within_r_squared=within_r_squared,
        exposure_estimate=float(coefficients[0]),
        exposure_standard_error=float(standard_errors[0]),
        results_output=results_output,
        sample_output=sample_output,
        metadata_output=metadata_output,
        text_output=text_output,
    )
