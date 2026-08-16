"""Build a dated municipality-year exposure panel.

The classifier deliberately keeps legal/procurement interpretation outside the
code.  Its job is narrower: validate reviewed evidence intervals, intersect
them with calendar years, apply four documented exposure rules and the
project-wide post-raid non-exposure rule, and emit long and wide balanced
panels.  A municipality is never carried forward merely because it was exposed
once.
"""

from __future__ import annotations

import calendar
import csv
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence


DEFAULT_START_YEAR = 2001
DEFAULT_END_YEAR = 2024
# The documented infringement periods end during March 2021.  Since an annual
# exposure indicator is positive when even one supported day overlaps the
# cartel, 2021 is a mixed year rather than a clean post-raid year.  Therefore
# 2022 is the first full calendar year known to be outside this cartel period.
FIRST_FULL_POST_RAID_YEAR = 2022


class InputError(ValueError):
    """Raised when an input file cannot be interpreted safely."""


@dataclass(frozen=True)
class BuildSummary:
    municipalities: int
    years: int
    rows: int
    exposed_rows: int
    ever_exposed_municipalities: int
    with_data_rows: int
    region_added_rows: int
    region_added_municipalities: int
    has_within_year_variation: bool
    has_within_gkz_variation: bool
    treatment_transitions: int
    year_fe_residual_variance_share: float
    main_output: Path
    wide_output: Path
    audit_output: Path | None
    diagnostics_output: Path


@dataclass(frozen=True)
class Interval:
    """Inclusive date interval; ``None`` denotes an open boundary."""

    start: date | None
    end: date | None


_YEAR = re.compile(r"^\d{4}$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_GKZ = re.compile(r"^\d{5}$")
RowKey = tuple[str, int]


def _read_csv(
    path: Path,
    required_columns: set[str],
    *,
    optional_file: bool,
) -> list[dict[str, str]]:
    if not path.exists():
        if optional_file:
            return []
        raise InputError(f"Required input is missing: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise InputError(f"{path} has no header row")
        fields = {field.strip() for field in reader.fieldnames if field is not None}
        missing = required_columns - fields
        if missing:
            raise InputError(
                f"{path} is missing required column(s): {', '.join(sorted(missing))}"
            )

        rows: list[dict[str, str]] = []
        for line_number, raw in enumerate(reader, start=2):
            row = {
                (key or "").strip(): (value or "").strip()
                for key, value in raw.items()
            }
            if not any(row.values()):
                continue
            row["_line"] = str(line_number)
            rows.append(row)
        return rows


def _context(path: Path, row: Mapping[str, str]) -> str:
    return f"{path}:{row.get('_line', '?')}"


def _normalize_gkz(value: str, context: str) -> str:
    cleaned = value.strip()
    if cleaned.isdigit() and 1 <= len(cleaned) <= 5:
        cleaned = cleaned.zfill(5)
    if not _GKZ.fullmatch(cleaned):
        raise InputError(f"{context}: GKZ must contain exactly five digits: {value!r}")
    return cleaned


def _parse_bool(value: str, context: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise InputError(f"{context}: expected a boolean (0/1 or true/false), got {value!r}")


def _parse_boundary(value: str, *, is_end: bool, context: str) -> date | None:
    value = value.strip()
    if not value:
        return None

    try:
        if _YEAR.fullmatch(value):
            year = int(value)
            return date(year, 12, 31) if is_end else date(year, 1, 1)

        match = _YEAR_MONTH.fullmatch(value)
        if match:
            year, month = (int(part) for part in match.groups())
            day = calendar.monthrange(year, month)[1] if is_end else 1
            return date(year, month, day)

        return date.fromisoformat(value)
    except ValueError as exc:
        raise InputError(
            f"{context}: invalid date {value!r}; use YYYY, YYYY-MM, or YYYY-MM-DD"
        ) from exc


def _parse_interval(
    row: Mapping[str, str],
    start_column: str,
    end_column: str,
    context: str,
) -> Interval:
    interval = Interval(
        start=_parse_boundary(row.get(start_column, ""), is_end=False, context=context),
        end=_parse_boundary(row.get(end_column, ""), is_end=True, context=context),
    )
    if interval.start is None and interval.end is None:
        raise InputError(
            f"{context}: at least one of {start_column} or {end_column} is required"
        )
    if (
        interval.start is not None
        and interval.end is not None
        and interval.start > interval.end
    ):
        raise InputError(f"{context}: {start_column} is after {end_column}")
    return interval


def _year_interval(year: int) -> Interval:
    return Interval(date(year, 1, 1), date(year, 12, 31))


def _overlaps_all(*intervals: Interval) -> bool:
    """Return whether inclusive intervals share at least one common date."""

    starts = [interval.start for interval in intervals if interval.start is not None]
    ends = [interval.end for interval in intervals if interval.end is not None]
    latest_start = max(starts) if starts else None
    earliest_end = min(ends) if ends else None
    return (
        latest_start is None
        or earliest_end is None
        or latest_start <= earliest_end
    )


def _overlapping_years(
    intervals: Sequence[Interval], start_year: int, end_year: int
) -> range:
    """Return panel years in the common intersection of ``intervals``."""

    starts = [
        interval.start.year
        for interval in intervals
        if interval.start is not None
    ]
    ends = [
        interval.end.year
        for interval in intervals
        if interval.end is not None
    ]
    first = max([start_year, *starts])
    last = min([end_year, *ends])
    if first > last:
        return range(0)
    # Year bounds alone can overstate an intersection when two intervals meet
    # in the same year but on disjoint dates.  Filter that edge case below.
    return range(first, last + 1)


def _require_identifier(
    row: Mapping[str, str], column: str, context: str
) -> str:
    value = row.get(column, "").strip()
    if not value:
        raise InputError(f"{context}: {column} cannot be blank")
    return value


def _check_known_gkz(gkz: str, universe: set[str], context: str) -> None:
    if gkz not in universe:
        raise InputError(
            f"{context}: GKZ {gkz} is not in municipalities.csv; "
            "check the harmonized territorial reference year"
        )


def _source_ids(*rows: Mapping[str, str]) -> list[str]:
    return [
        row["source_id"].strip()
        for row in rows
        if row.get("source_id", "").strip()
    ]


def _join_unique(values: Iterable[str]) -> str:
    return "|".join(sorted(set(value for value in values if value)))


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


def _validate_year_range(start_year: int, end_year: int) -> None:
    if not (1 <= start_year <= 9999 and 1 <= end_year <= 9999):
        raise InputError("Panel years must be between 1 and 9999")
    if start_year > end_year:
        raise InputError("start_year cannot be after end_year")


def build_exposure(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    start_year: int = DEFAULT_START_YEAR,
    end_year: int = DEFAULT_END_YEAR,
    include_data_found: bool = True,
    write_audit: bool = True,
) -> BuildSummary:
    """Build long/wide GKZ-year outputs and an optional rule-level audit file.

    Every municipality in ``municipalities.csv`` receives one row for every
    inclusive panel year.  A rule applies to a year if its dated source
    intervals share at least one day with that calendar year.  Every full
    calendar year from 2022 onward is a known, non-exposed post-raid period for
    all municipalities.  The partial 2021 post-raid period does not establish
    an annual zero because exposure earlier in 2021 remains possible.
    """

    _validate_year_range(start_year, end_year)
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    municipalities_path = input_dir / "municipalities.csv"
    direct_path = input_dir / "direct_evidence.csv"
    periods_path = input_dir / "cartel_periods.csv"
    contracts_path = input_dir / "contracts.csv"
    association_exposure_path = input_dir / "association_exposure.csv"
    memberships_path = input_dir / "association_memberships.csv"
    regional_path = input_dir / "regional_exposure.csv"

    municipality_rows = _read_csv(
        municipalities_path, {"gkz"}, optional_file=False
    )
    if not municipality_rows:
        raise InputError(f"{municipalities_path} contains no municipalities")

    names: dict[str, str] = {}
    for row in municipality_rows:
        context = _context(municipalities_path, row)
        gkz = _normalize_gkz(row["gkz"], context)
        if gkz in names:
            raise InputError(f"{context}: duplicate municipality GKZ {gkz}")
        names[gkz] = row.get("municipality_name", "")
    universe = set(names)

    direct_rows = _read_csv(
        direct_path,
        {"gkz", "exposed", "exposure_start", "exposure_end"},
        optional_file=True,
    )
    period_rows = _read_csv(
        periods_path,
        {"participant_id", "cartel_start", "cartel_end"},
        optional_file=True,
    )
    contract_rows = _read_csv(
        contracts_path,
        {"gkz", "participant_id", "contract_start", "contract_end"},
        optional_file=True,
    )
    association_rows = _read_csv(
        association_exposure_path,
        {"association_id", "exposed", "exposure_start", "exposure_end"},
        optional_file=True,
    )
    membership_rows = _read_csv(
        memberships_path,
        {"gkz", "association_id", "membership_start", "membership_end"},
        optional_file=True,
    )
    regional_rows = _read_csv(
        regional_path,
        {
            "region_type",
            "region_code",
            "exposure_start",
            "exposure_end",
            "legal_status",
            "eligible_for_exposure",
        },
        optional_file=True,
    )

    data_found: set[RowKey] = set()
    direct_positive: set[RowKey] = set()
    contract_positive: set[RowKey] = set()
    association_positive: set[RowKey] = set()
    regional_positive: set[RowKey] = set()
    positive_sources: defaultdict[RowKey, list[str]] = defaultdict(list)
    direct_count: defaultdict[RowKey, int] = defaultdict(int)
    contract_count: defaultdict[RowKey, int] = defaultdict(int)
    association_count: defaultdict[RowKey, int] = defaultdict(int)
    regional_count: defaultdict[RowKey, int] = defaultdict(int)

    for row in regional_rows:
        context = _context(regional_path, row)
        if row["region_type"] != "state":
            raise InputError(f"{context}: region_type must be state")
        region_code = row["region_code"]
        if len(region_code) != 1 or region_code not in "123456789":
            raise InputError(
                f"{context}: state region_code must be a one-digit GKZ prefix"
            )
        interval = _parse_interval(row, "exposure_start", "exposure_end", context)
        status = row["legal_status"]
        if status not in {"final", "pending_admitted"}:
            raise InputError(
                f"{context}: legal_status must be final or pending_admitted"
            )
        eligible = _parse_bool(row["eligible_for_exposure"], context)
        if status != "final" and eligible:
            raise InputError(
                f"{context}: a non-final regional rule cannot be "
                "eligible_for_exposure"
            )
        if not eligible:
            continue
        for gkz in universe:
            if not gkz.startswith(region_code):
                continue
            for year in _overlapping_years([interval], start_year, end_year):
                if not _overlaps_all(interval, _year_interval(year)):
                    continue
                key = (gkz, year)
                regional_positive.add(key)
                data_found.add(key)
                regional_count[key] += 1
                positive_sources[key].extend(_source_ids(row))

    for row in direct_rows:
        context = _context(direct_path, row)
        gkz = _normalize_gkz(row["gkz"], context)
        _check_known_gkz(gkz, universe, context)
        interval = _parse_interval(
            row, "exposure_start", "exposure_end", context
        )
        exposed = _parse_bool(row["exposed"], context)
        for year in _overlapping_years([interval], start_year, end_year):
            year_span = _year_interval(year)
            if not _overlaps_all(interval, year_span):
                continue
            key = (gkz, year)
            data_found.add(key)
            direct_count[key] += 1
            if exposed:
                direct_positive.add(key)
                positive_sources[key].extend(_source_ids(row))

    periods_by_participant: defaultdict[
        str, list[tuple[Interval, frozenset[str], Mapping[str, str]]]
    ] = defaultdict(list)
    for row in period_rows:
        context = _context(periods_path, row)
        participant_id = _require_identifier(row, "participant_id", context)
        interval = _parse_interval(row, "cartel_start", "cartel_end", context)
        legal_status = row.get("legal_status", "").strip() or "final"
        if legal_status not in {"final", "pending_admitted"}:
            raise InputError(
                f"{context}: legal_status must be final or pending_admitted"
            )
        eligible = _parse_bool(
            row.get("eligible_for_exposure", "").strip() or "true",
            context,
        )
        if legal_status != "final" and eligible:
            raise InputError(
                f"{context}: a non-final participant period cannot be "
                "eligible_for_exposure"
            )
        prefixes = [
            value.strip()
            for value in row.get("gkz_prefixes", "").split("|")
            if value.strip()
        ]
        if len(prefixes) != len(set(prefixes)) or any(
            len(value) != 1 or value not in "123456789"
            for value in prefixes
        ):
            raise InputError(
                f"{context}: gkz_prefixes must be unique one-digit state "
                "prefixes separated by |"
            )
        if eligible:
            periods_by_participant[participant_id].append(
                (interval, frozenset(prefixes), row)
            )

    for row in contract_rows:
        context = _context(contracts_path, row)
        gkz = _normalize_gkz(row["gkz"], context)
        _check_known_gkz(gkz, universe, context)
        # A blank participant is an affirmative reviewed award to a supplier
        # outside the eligible cartel roster.  It establishes coverage over
        # the supported performance interval but can never trigger exposure.
        participant_id = row.get("participant_id", "").strip()
        contract_interval = _parse_interval(
            row, "contract_start", "contract_end", context
        )
        for year in _overlapping_years([contract_interval], start_year, end_year):
            year_span = _year_interval(year)
            if not _overlaps_all(contract_interval, year_span):
                continue
            key = (gkz, year)
            data_found.add(key)
            contract_count[key] += 1

            for cartel_interval, prefixes, period_row in periods_by_participant.get(
                participant_id, []
            ):
                if prefixes and gkz[0] not in prefixes:
                    continue
                if _overlaps_all(contract_interval, cartel_interval, year_span):
                    contract_positive.add(key)
                    positive_sources[key].extend(_source_ids(row, period_row))

    exposures_by_association: defaultdict[
        str, list[tuple[bool, Interval, Mapping[str, str]]]
    ] = defaultdict(list)
    for row in association_rows:
        context = _context(association_exposure_path, row)
        association_id = _require_identifier(row, "association_id", context)
        exposed = _parse_bool(row["exposed"], context)
        interval = _parse_interval(
            row, "exposure_start", "exposure_end", context
        )
        exposures_by_association[association_id].append((exposed, interval, row))

    for row in membership_rows:
        context = _context(memberships_path, row)
        gkz = _normalize_gkz(row["gkz"], context)
        _check_known_gkz(gkz, universe, context)
        association_id = _require_identifier(row, "association_id", context)
        membership_interval = _parse_interval(
            row, "membership_start", "membership_end", context
        )
        for exposed, exposure_interval, exposure_row in exposures_by_association.get(
            association_id, []
        ):
            intervals = [membership_interval, exposure_interval]
            for year in _overlapping_years(intervals, start_year, end_year):
                year_span = _year_interval(year)
                if not _overlaps_all(*intervals, year_span):
                    continue
                key = (gkz, year)
                data_found.add(key)
                association_count[key] += 1
                if exposed:
                    association_positive.add(key)
                    positive_sources[key].extend(_source_ids(row, exposure_row))

    main_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    ever_exposed: set[str] = set()
    for gkz in sorted(universe):
        wide_row: dict[str, object] = {
            "gkz": gkz,
            "municipality_name": names[gkz],
        }
        for year in range(start_year, end_year + 1):
            key = (gkz, year)
            direct = key in direct_positive
            contract = key in contract_positive
            association = key in association_positive
            regional = key in regional_positive
            exposure_direct = direct or contract or association
            exposed = exposure_direct or regional
            post_raid = year >= FIRST_FULL_POST_RAID_YEAR
            if post_raid and exposed:
                raise InputError(
                    f"{gkz} in {year}: positive exposure conflicts with the "
                    "project-wide post-raid non-exposure rule; review the "
                    "dated evidence"
                )
            found = key in data_found or post_raid
            direct_found = bool(
                direct_count[key] or contract_count[key] or association_count[key]
            ) or post_raid
            regional_found = bool(regional_count[key]) or post_raid
            if exposed and not found:  # Defensive assertion for future rule changes.
                raise AssertionError(
                    f"Positive exposure without data_found for {gkz} in {year}"
                )
            if exposed:
                ever_exposed.add(gkz)

            reasons = []
            if direct:
                reasons.append("direct:municipality")
            if contract:
                reasons.append("direct:contract")
            if association:
                reasons.append("direct:association")
            if regional:
                reasons.append("regional:state")
            main_row: dict[str, object] = {
                "gkz": gkz,
                "year": year,
                "exposure_direct": int(exposure_direct),
                "exposure_regional": int(regional),
                "exposure": int(exposed),
                "exposure_basis": "|".join(reasons),
            }
            if include_data_found:
                main_row["data_found"] = str(found).lower()
                main_row["data_found_direct"] = str(direct_found).lower()
                main_row["data_found_regional"] = str(regional_found).lower()
            main_rows.append(main_row)
            wide_row[str(year)] = int(exposed)

            data_found_reasons = []
            if direct_count[key]:
                data_found_reasons.append("direct")
            if contract_count[key]:
                data_found_reasons.append("contract")
            if association_count[key]:
                data_found_reasons.append("association")
            if regional_count[key]:
                data_found_reasons.append("regional")
            if post_raid:
                data_found_reasons.append("post_raid")
            audit_rows.append(
                {
                    "gkz": gkz,
                    "year": year,
                    "municipality_name": names[gkz],
                    "exposure": int(exposed),
                    "data_found": str(found).lower(),
                    "data_found_direct": str(direct_found).lower(),
                    "data_found_regional": str(regional_found).lower(),
                    "direct_exposure": int(direct),
                    "contract_exposure": int(contract),
                    "association_exposure": int(association),
                    "regional_exposure": int(regional),
                    "exposure_direct": int(exposure_direct),
                    "exposure_regional": int(regional),
                    "regional_added_exposure": int(regional and not exposure_direct),
                    "exposure_reasons": "|".join(reasons),
                    "data_found_reasons": "|".join(data_found_reasons),
                    "post_raid_non_exposure": int(post_raid),
                    "positive_source_ids": _join_unique(positive_sources[key]),
                    "direct_rows": direct_count[key],
                    "contract_rows": contract_count[key],
                    "evaluated_association_memberships": association_count[key],
                    "regional_rules": regional_count[key],
                }
            )
        wide_rows.append(wide_row)

    main_output = output_dir / "municipality_year_exposure.csv"
    main_fields = [
        "gkz",
        "year",
        "exposure_direct",
        "exposure_regional",
        "exposure",
        "exposure_basis",
    ]
    if include_data_found:
        main_fields.extend(
            ["data_found", "data_found_direct", "data_found_regional"]
        )
    _write_csv_atomic(main_output, main_fields, main_rows)

    wide_output = output_dir / "municipality_year_exposure_wide.csv"
    _write_csv_atomic(
        wide_output,
        [
            "gkz",
            "municipality_name",
            *(str(year) for year in range(start_year, end_year + 1)),
        ],
        wide_rows,
    )

    audit_output: Path | None = None
    if write_audit:
        audit_output = output_dir / "municipality_year_exposure_audit.csv"
        _write_csv_atomic(
            audit_output,
            [
                "gkz",
                "year",
                "municipality_name",
                "exposure",
                "exposure_direct",
                "exposure_regional",
                "data_found",
                "data_found_direct",
                "data_found_regional",
                "direct_exposure",
                "contract_exposure",
                "association_exposure",
                "regional_exposure",
                "regional_added_exposure",
                "exposure_reasons",
                "data_found_reasons",
                "post_raid_non_exposure",
                "positive_source_ids",
                "direct_rows",
                "contract_rows",
                "evaluated_association_memberships",
                "regional_rules",
            ],
            audit_rows,
        )

    diagnostic_rows: list[dict[str, object]] = []
    for year in range(start_year, end_year + 1):
        rows = [row for row in main_rows if row["year"] == year]
        direct_total = sum(int(row["exposure_direct"]) for row in rows)
        regional_total = sum(int(row["exposure_regional"]) for row in rows)
        combined_total = sum(int(row["exposure"]) for row in rows)
        exposed_states = sorted(
            {str(row["gkz"])[0] for row in rows if row["exposure_regional"]}
        )
        diagnostic_rows.append(
            {
                "year": year,
                "municipalities": len(rows),
                "exposure_direct_municipalities": direct_total,
                "exposure_regional_municipalities": regional_total,
                "exposure_combined_municipalities": combined_total,
                "regional_bundesland_codes": "|".join(exposed_states),
                "regional_bundeslaender": len(exposed_states),
                "direct_share": f"{direct_total / len(rows):.10f}",
                "regional_share": f"{regional_total / len(rows):.10f}",
                "combined_share": f"{combined_total / len(rows):.10f}",
                "regional_universal": str(regional_total == len(rows)).lower(),
                "combined_universal": str(combined_total == len(rows)).lower(),
                "combined_within_year_variation": str(
                    0 < combined_total < len(rows)
                ).lower(),
            }
        )
    diagnostics_output = output_dir / "municipality_year_exposure_diagnostics.csv"
    _write_csv_atomic(
        diagnostics_output,
        [
            "year",
            "municipalities",
            "exposure_direct_municipalities",
            "exposure_regional_municipalities",
            "exposure_combined_municipalities",
            "regional_bundesland_codes",
            "regional_bundeslaender",
            "direct_share",
            "regional_share",
            "combined_share",
            "regional_universal",
            "combined_universal",
            "combined_within_year_variation",
        ],
        diagnostic_rows,
    )

    exposure_by_year: defaultdict[int, set[int]] = defaultdict(set)
    exposure_by_gkz: defaultdict[str, set[int]] = defaultdict(set)
    exposure_sequence_by_gkz: defaultdict[str, list[int]] = defaultdict(list)
    exposure_sum_by_year: defaultdict[int, int] = defaultdict(int)
    for row in main_rows:
        year = int(row["year"])
        gkz = str(row["gkz"])
        value = int(row["exposure"])
        exposure_by_year[year].add(value)
        exposure_by_gkz[gkz].add(value)
        exposure_sequence_by_gkz[gkz].append(value)
        exposure_sum_by_year[year] += value
    added_keys = regional_positive - (
        direct_positive | contract_positive | association_positive
    )
    transitions = 0
    for values in exposure_sequence_by_gkz.values():
        transitions += sum(left != right for left, right in zip(values, values[1:]))
    exposure_values = [float(row["exposure"]) for row in main_rows]
    grand_mean = sum(exposure_values) / len(exposure_values)
    total_ss = sum((value - grand_mean) ** 2 for value in exposure_values)
    year_means = {
        year: exposure_sum_by_year[year] / len(universe)
        for year in range(start_year, end_year + 1)
    }
    residual_ss = sum(
        (float(row["exposure"]) - year_means[int(row["year"])]) ** 2
        for row in main_rows
    )
    return BuildSummary(
        municipalities=len(universe),
        years=end_year - start_year + 1,
        rows=len(main_rows),
        exposed_rows=sum(int(row["exposure"]) for row in main_rows),
        ever_exposed_municipalities=len(ever_exposed),
        with_data_rows=sum(row["data_found"] == "true" for row in audit_rows),
        region_added_rows=len(added_keys),
        region_added_municipalities=len({gkz for gkz, _ in added_keys}),
        has_within_year_variation=any(
            len(values) > 1 for values in exposure_by_year.values()
        ),
        has_within_gkz_variation=any(
            len(values) > 1 for values in exposure_by_gkz.values()
        ),
        treatment_transitions=transitions,
        year_fe_residual_variance_share=(
            residual_ss / total_ss if total_ss else 0.0
        ),
        main_output=main_output,
        wide_output=wide_output,
        audit_output=audit_output,
        diagnostics_output=diagnostics_output,
    )
