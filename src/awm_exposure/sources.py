"""Reproducible source acquisition and raw-input normalization.

The official evidence is heterogeneous:

* Statistics Austria publishes a machine-readable municipality universe.
* Cartel decisions are long HTML documents containing anonymised firms, tables,
  addresses, and incidental place names.
* Procurement and association records have no complete national historical
  register.

For that reason this module deliberately does *not* label every place-name hit
in a court document as exposure.  Such a shortcut would turn company addresses
and project locations into false positives.  Instead, ``registry.csv`` defines
immutable official downloads and ``curated/*.csv`` records the narrow
source-backed propositions a researcher has reviewed.  The builder resolves
those reviewed municipality names against one official GKZ vintage, validates
all citations, and emits exactly the schemas consumed by the exposure builder.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from zipfile import BadZipFile, ZipFile

import httpx
import shapefile


class SourceDataError(ValueError):
    """Raised when a source cannot be downloaded or normalized safely."""


@dataclass(frozen=True)
class DownloadSummary:
    downloaded: int
    cached: int
    manifest_path: Path


@dataclass(frozen=True)
class RawBuildSummary:
    municipalities: int
    evidence_rows: int
    raw_dir: Path


RAW_SCHEMAS: dict[str, list[str]] = {
    "municipalities.csv": ["gkz", "municipality_name"],
    "direct_evidence.csv": [
        "gkz",
        "exposed",
        "source_id",
        "source_url",
        "notes",
    ],
    "cartel_periods.csv": [
        "participant_id",
        "participant_name",
        "cartel_start",
        "cartel_end",
        "source_id",
        "source_url",
        "notes",
    ],
    "contracts.csv": [
        "gkz",
        "participant_id",
        "contract_start",
        "contract_end",
        "source_id",
        "source_url",
        "notes",
    ],
    "association_exposure.csv": [
        "association_id",
        "association_name",
        "exposed",
        "exposure_start",
        "exposure_end",
        "source_id",
        "source_url",
        "notes",
    ],
    "association_memberships.csv": [
        "gkz",
        "association_id",
        "membership_start",
        "membership_end",
        "source_id",
        "source_url",
        "notes",
    ],
}

_CURATED_SCHEMAS: dict[str, set[str]] = {
    "direct_evidence.csv": {"municipality_name", "exposed", "source_id"},
    "cartel_periods.csv": {
        "participant_id",
        "cartel_start",
        "cartel_end",
        "source_id",
    },
    "contracts.csv": {
        "municipality_name",
        "participant_id",
        "contract_start",
        "contract_end",
        "source_id",
    },
    "association_exposure.csv": {
        "association_id",
        "exposed",
        "exposure_start",
        "exposure_end",
        "source_id",
    },
    "association_memberships.csv": {
        "municipality_name",
        "association_id",
        "membership_start",
        "membership_end",
        "source_id",
    },
}


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.exists():
        raise SourceDataError(f"Required source table is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SourceDataError(f"{path} has no header row")
        fields = {field.strip() for field in reader.fieldnames if field}
        missing = required - fields
        if missing:
            raise SourceDataError(
                f"{path} is missing column(s): {', '.join(sorted(missing))}"
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


def _safe_target(root: Path, relative_name: str) -> Path:
    if not relative_name:
        raise SourceDataError("A registry filename cannot be blank")
    root = root.resolve()
    target = (root / relative_name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SourceDataError(
            f"Registry filename escapes the sources directory: {relative_name!r}"
        ) from exc
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _write_text_atomic(path: Path, content: str) -> None:
    _write_bytes_atomic(path, content.encode("utf-8"))


def _write_csv_atomic(
    path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]
) -> None:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    _write_text_atomic(path, output.getvalue())


def _load_registry(sources_dir: Path) -> list[dict[str, str]]:
    rows = _read_csv(
        sources_dir / "registry.csv",
        {"source_id", "source_url", "filename", "description"},
    )
    seen: set[str] = set()
    for row in rows:
        source_id = row["source_id"]
        if not source_id:
            raise SourceDataError(
                f"{sources_dir / 'registry.csv'}:{row['_line']}: blank source_id"
            )
        if source_id in seen:
            raise SourceDataError(f"Duplicate source_id in registry: {source_id}")
        seen.add(source_id)
        _safe_target(sources_dir, row["filename"])
        if not row["source_url"].startswith("https://"):
            raise SourceDataError(
                f"Source URLs must use HTTPS ({source_id}: {row['source_url']!r})"
            )
    return rows


def download_sources(
    sources_dir: Path | str,
    *,
    refresh: bool = False,
    client: httpx.Client | None = None,
) -> DownloadSummary:
    """Download every registered source and write a checksum manifest.

    Existing snapshots are reused by default.  This makes ordinary builds fast
    and preserves the exact legal evidence previously reviewed.  ``--refresh``
    is an explicit decision to replace those snapshots with current server
    content; the changed SHA-256 digest is then visible in the manifest.
    """

    sources_dir = Path(sources_dir)
    registry = _load_registry(sources_dir)
    manifest_path = sources_dir / "download_manifest.json"
    prior: dict[str, object] = {}
    if manifest_path.exists():
        try:
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SourceDataError(f"Cannot read {manifest_path}: {exc}") from exc
    prior_entries = {
        item.get("source_id"): item
        for item in prior.get("sources", [])
        if isinstance(item, dict)
    }

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(90.0),
            headers={
                "User-Agent": (
                    "awm-regression/0.2 "
                    "(academic reproducibility; source contact in repository)"
                )
            },
        )

    downloaded = 0
    cached = 0
    entries: list[dict[str, object]] = []
    try:
        for source in registry:
            target = _safe_target(sources_dir, source["filename"])
            fetched_at: str
            if target.exists() and not refresh:
                cached += 1
                previous = prior_entries.get(source["source_id"], {})
                fetched_at = str(previous.get("fetched_at") or "")
            else:
                try:
                    response = client.get(source["source_url"])
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise SourceDataError(
                        f"Failed to download {source['source_id']} "
                        f"from {source['source_url']}: {exc}"
                    ) from exc
                if not response.content:
                    raise SourceDataError(
                        f"Downloaded source is empty: {source['source_id']}"
                    )
                _write_bytes_atomic(target, response.content)
                downloaded += 1
                fetched_at = datetime.now(UTC).isoformat()

            entries.append(
                {
                    "source_id": source["source_id"],
                    "source_url": source["source_url"],
                    "filename": source["filename"],
                    "description": source["description"],
                    "fetched_at": fetched_at,
                    "bytes": target.stat().st_size,
                    "sha256": _sha256(target),
                }
            )
    finally:
        if owns_client:
            client.close()

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": entries,
    }
    _write_text_atomic(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return DownloadSummary(downloaded, cached, manifest_path)


def _municipalities_from_zip(path: Path) -> list[dict[str, str]]:
    """Read the ID/NAME attributes from Statistics Austria's SHAPE-ZIP.

    Geometry is intentionally ignored: the regression needs only the official
    GKZ universe and names.  Reading the DBF directly avoids a heavyweight GIS
    dependency and prevents coordinate-system details from affecting the CSV.
    """

    if not path.exists():
        raise SourceDataError(
            f"Municipality snapshot is missing: {path}; run `uv run awm-sources download`"
        )
    try:
        with ZipFile(path) as archive:
            by_suffix: dict[str, str] = {}
            for member in archive.namelist():
                suffix = Path(member).suffix.lower()
                if suffix in {".shp", ".shx", ".dbf"}:
                    by_suffix[suffix] = member
            missing = {".shp", ".dbf"} - by_suffix.keys()
            if missing:
                raise SourceDataError(
                    f"{path} lacks required shapefile member(s): "
                    f"{', '.join(sorted(missing))}"
                )
            kwargs: dict[str, io.BytesIO] = {
                "shp": io.BytesIO(archive.read(by_suffix[".shp"])),
                "dbf": io.BytesIO(archive.read(by_suffix[".dbf"])),
            }
            if ".shx" in by_suffix:
                kwargs["shx"] = io.BytesIO(archive.read(by_suffix[".shx"]))
            reader = shapefile.Reader(**kwargs)
            field_lookup = {
                field[0].upper(): field[0] for field in reader.fields[1:]
            }
            id_field = field_lookup.get("ID") or field_lookup.get("G_ID")
            name_field = field_lookup.get("NAME") or field_lookup.get("G_NAME")
            if id_field is None or name_field is None:
                raise SourceDataError(
                    f"{path} must contain Statistics Austria ID/NAME "
                    f"(or G_ID/G_NAME) fields; "
                    f"found {', '.join(field_lookup)}"
                )
            rows_by_gkz: dict[str, dict[str, str]] = {}
            for record in reader.iterRecords():
                values = record.as_dict()
                raw_gkz = str(values[id_field]).strip()
                if raw_gkz.endswith(".0"):
                    raw_gkz = raw_gkz[:-2]
                gkz = raw_gkz.zfill(5)
                name = str(values[name_field]).strip()
                if len(gkz) != 5 or not gkz.isdigit() or not name:
                    raise SourceDataError(
                        f"Invalid municipality record in {path}: {raw_gkz!r}, {name!r}"
                    )
                # The geometry service represents Vienna by its 23 municipal
                # districts (90101--92301), although Austria's municipality
                # universe treats Vienna as one municipality, GKZ 90001.
                # Collapse those polygons here so the output matches Statistics
                # Austria's published national municipality count.
                if gkz.startswith("9"):
                    gkz = "90001"
                    name = "Wien"
                candidate = {"gkz": gkz, "municipality_name": name}
                previous = rows_by_gkz.get(gkz)
                if previous is not None and previous != candidate:
                    raise SourceDataError(
                        f"Conflicting records for GKZ {gkz} in {path}"
                    )
                rows_by_gkz[gkz] = candidate
    except BadZipFile as exc:
        raise SourceDataError(f"Municipality source is not a valid ZIP: {path}") from exc

    rows = sorted(rows_by_gkz.values(), key=lambda row: row["gkz"])
    return rows


def _validate_source(
    row: Mapping[str, str],
    path: Path,
    registry: Mapping[str, Mapping[str, str]],
) -> str:
    source_id = row.get("source_id", "").strip()
    if source_id not in registry:
        raise SourceDataError(
            f"{path}:{row.get('_line', '?')}: unknown source_id {source_id!r}"
        )
    return source_id


def _resolve_gkz(
    row: Mapping[str, str],
    path: Path,
    gkz_by_name: Mapping[str, Sequence[str]],
    municipality_names: Mapping[str, str],
) -> str:
    supplied_gkz = row.get("gkz", "").strip()
    supplied_name = row.get("municipality_name", "").strip()
    if supplied_gkz:
        gkz = supplied_gkz.zfill(5)
        if gkz not in municipality_names:
            raise SourceDataError(
                f"{path}:{row.get('_line', '?')}: unknown GKZ {gkz}"
            )
        if supplied_name and municipality_names[gkz] != supplied_name:
            raise SourceDataError(
                f"{path}:{row.get('_line', '?')}: GKZ {gkz} is "
                f"{municipality_names[gkz]!r}, not {supplied_name!r}"
            )
        return gkz
    candidates = gkz_by_name.get(supplied_name, ())
    if not candidates:
        raise SourceDataError(
            f"{path}:{row.get('_line', '?')}: municipality name "
            f"{supplied_name!r} is not an exact match in the selected GKZ vintage"
        )
    if len(candidates) > 1:
        raise SourceDataError(
            f"{path}:{row.get('_line', '?')}: municipality name "
            f"{supplied_name!r} is ambiguous (GKZ {', '.join(candidates)}); "
            "add the official gkz to this curated row"
        )
    return candidates[0]


def _deduplicate_and_sort(
    rows: list[dict[str, str]], fieldnames: Sequence[str]
) -> list[dict[str, str]]:
    unique: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(row.get(field, "") for field in fieldnames)
        unique[key] = row
    return [unique[key] for key in sorted(unique)]


def _manifest_entries(sources_dir: Path) -> dict[str, dict[str, object]]:
    path = sources_dir / "download_manifest.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SourceDataError(f"Cannot read {path}: {exc}") from exc
    return {
        str(item["source_id"]): item
        for item in payload.get("sources", [])
        if isinstance(item, dict) and item.get("source_id")
    }


def build_raw_data(
    sources_dir: Path | str,
    raw_dir: Path | str,
    *,
    municipality_source_id: str = "statistik_austria_municipalities_2026",
) -> RawBuildSummary:
    """Build all six raw CSVs from downloaded and reviewed source records."""

    sources_dir = Path(sources_dir)
    raw_dir = Path(raw_dir)
    registry_rows = _load_registry(sources_dir)
    registry = {row["source_id"]: row for row in registry_rows}
    if municipality_source_id not in registry:
        raise SourceDataError(
            f"Municipality source_id is not registered: {municipality_source_id}"
        )

    municipality_path = _safe_target(
        sources_dir, registry[municipality_source_id]["filename"]
    )
    municipalities = _municipalities_from_zip(municipality_path)
    municipality_names = {
        row["gkz"]: row["municipality_name"] for row in municipalities
    }
    gkz_by_name: dict[str, list[str]] = {}
    for row in municipalities:
        gkz_by_name.setdefault(row["municipality_name"], []).append(row["gkz"])

    output: dict[str, list[dict[str, str]]] = {
        name: [] for name in RAW_SCHEMAS
    }
    output["municipalities.csv"] = municipalities
    curated_dir = sources_dir / "curated"

    for filename, required in _CURATED_SCHEMAS.items():
        path = curated_dir / filename
        rows = _read_csv(path, required)
        target_rows = output[filename]
        for row in rows:
            source_id = _validate_source(row, path, registry)
            normalized = {field: row.get(field, "") for field in RAW_SCHEMAS[filename]}
            normalized["source_id"] = source_id
            normalized["source_url"] = (
                row.get("source_url", "") or registry[source_id]["source_url"]
            )
            if filename in {
                "direct_evidence.csv",
                "contracts.csv",
                "association_memberships.csv",
            }:
                normalized["gkz"] = _resolve_gkz(
                    row, path, gkz_by_name, municipality_names
                )
            target_rows.append(normalized)

    raw_dir.mkdir(parents=True, exist_ok=True)
    for filename, fieldnames in RAW_SCHEMAS.items():
        rows = _deduplicate_and_sort(output[filename], fieldnames)
        _write_csv_atomic(raw_dir / filename, fieldnames, rows)

    # The raw source log makes a source_id resolvable without relying on a URL
    # that might later change.  A blank checksum indicates `build` was run
    # before `download`; normal `all` runs populate every checksum.
    manifest = _manifest_entries(sources_dir)
    source_log_rows = []
    for row in registry_rows:
        entry = manifest.get(row["source_id"], {})
        source_log_rows.append(
            {
                "source_id": row["source_id"],
                "source_url": row["source_url"],
                "local_path": row["filename"],
                "fetched_at": entry.get("fetched_at", ""),
                "sha256": entry.get("sha256", ""),
                "description": row["description"],
            }
        )
    _write_csv_atomic(
        raw_dir / "source_log.csv",
        [
            "source_id",
            "source_url",
            "local_path",
            "fetched_at",
            "sha256",
            "description",
        ],
        source_log_rows,
    )

    evidence_rows = sum(
        len(output[filename])
        for filename in RAW_SCHEMAS
        if filename != "municipalities.csv"
    )
    return RawBuildSummary(len(municipalities), evidence_rows, raw_dir)
