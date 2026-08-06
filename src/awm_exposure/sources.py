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
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import httpx
import shapefile


class SourceDataError(ValueError):
    """Raised when a source cannot be downloaded or normalized safely."""


@dataclass(frozen=True)
class DownloadSummary:
    downloaded: int
    cached: int
    citation_only: int
    manifest_path: Path


@dataclass(frozen=True)
class RawBuildSummary:
    municipalities: int
    crosswalk_rows: int
    evidence_rows: int
    raw_dir: Path


@dataclass(frozen=True)
class ValidationSummary:
    registered_sources: int
    verified_downloads: int
    citation_only_sources: int
    curated_rows: int


RAW_SCHEMAS: dict[str, list[str]] = {
    "municipalities.csv": ["gkz", "municipality_name"],
    "direct_evidence.csv": [
        "gkz",
        "exposed",
        "exposure_start",
        "exposure_end",
        "source_id",
        "source_url",
        "notes",
    ],
    "cartel_periods.csv": [
        "participant_id",
        "participant_name",
        "cartel_start",
        "cartel_end",
        "legal_status",
        "eligible_for_exposure",
        "gkz_prefixes",
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
    "municipality_crosswalk.csv": [
        "historical_gkz",
        "historical_name",
        "current_gkz",
        "current_name",
        "mapping_status",
        "effective_dates",
        "change_reasons",
        "source_id",
        "source_url",
    ],
}

_CURATED_SCHEMAS: dict[str, set[str]] = {
    "direct_evidence.csv": {
        "municipality_name",
        "exposed",
        "exposure_start",
        "exposure_end",
        "source_id",
    },
    "cartel_periods.csv": {
        "participant_id",
        "cartel_start",
        "cartel_end",
        "legal_status",
        "eligible_for_exposure",
        "gkz_prefixes",
        "source_id",
    },
    "contracts.csv": {
        "municipality_name",
        "participant_id",
        "contract_start",
        "contract_end",
        "review_status",
        "reviewer",
        "reviewed_at",
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

_SUPPORT_SCHEMAS: dict[str, set[str]] = {
    "curated/participant_aliases.csv": {
        "participant_id",
        "alias",
        "source_id",
    },
    "review/fcc_public_project_review.csv": {
        "source_year",
        "project_name",
        "review_status",
        "disposition",
        "target_id",
        "source_id",
    },
}

_LEGAL_STATUSES = {"final", "pending_admitted"}
_REVIEW_STATUSES = {"accepted", "pending", "rejected"}
_FCC_REVIEW_STATUSES = {"accepted", "pending", "excluded"}
_ACQUISITION_METHODS = {"download", "citation_only"}


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


def _validate_download_content(path: Path, content: bytes) -> None:
    """Reject common server-error payloads before they enter the source cache."""

    suffix = path.suffix.lower()
    if suffix == ".zip" and not content.startswith(b"PK"):
        raise SourceDataError(
            f"Downloaded content for {path.name} is not a ZIP archive"
        )
    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise SourceDataError(f"Downloaded content for {path.name} is not a PDF")
    if suffix in {".html", ".htm"}:
        prefix = content[:8192].lower()
        if b"<html" not in prefix and b"<!doctype html" not in prefix:
            raise SourceDataError(
                f"Downloaded content for {path.name} is not recognizable HTML"
            )


def _validate_cached_snapshot(
    path: Path,
    source_id: str,
    manifest_entry: Mapping[str, object] | None,
) -> None:
    with path.open("rb") as handle:
        content_prefix = handle.read(8192)
    _validate_download_content(path, content_prefix)
    if not manifest_entry:
        return

    expected_bytes = manifest_entry.get("bytes")
    if expected_bytes not in (None, ""):
        try:
            expected_size = int(expected_bytes)
        except (TypeError, ValueError) as exc:
            raise SourceDataError(
                f"Download manifest has an invalid byte size for {source_id}"
            ) from exc
        if path.stat().st_size != expected_size:
            raise SourceDataError(
                f"Cached snapshot size changed for {source_id}; "
                "run with --refresh to replace it intentionally"
            )
    expected_sha = str(manifest_entry.get("sha256") or "")
    if expected_sha and (
        len(expected_sha) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha)
    ):
        raise SourceDataError(
            f"Download manifest has an invalid SHA-256 for {source_id}"
        )
    if expected_sha and _sha256(path) != expected_sha:
        raise SourceDataError(
            f"Cached snapshot checksum changed for {source_id}; "
            "run with --refresh to replace it intentionally"
        )


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
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    _write_text_atomic(path, output.getvalue())


def _load_registry(sources_dir: Path) -> list[dict[str, str]]:
    rows = _read_csv(
        sources_dir / "registry.csv",
        {
            "source_id",
            "source_url",
            "filename",
            "acquisition_method",
            "supporting_snapshot_id",
            "description",
        },
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
        if not row["source_url"].startswith("https://"):
            raise SourceDataError(
                f"Source URLs must use HTTPS ({source_id}: {row['source_url']!r})"
            )
        acquisition_method = row["acquisition_method"]
        if acquisition_method not in _ACQUISITION_METHODS:
            raise SourceDataError(
                f"Registry acquisition_method for {source_id} must be one of "
                f"{', '.join(sorted(_ACQUISITION_METHODS))}"
            )
        if acquisition_method == "download":
            _safe_target(sources_dir, row["filename"])
            if row["supporting_snapshot_id"]:
                raise SourceDataError(
                    f"Download source {source_id} cannot declare a "
                    "supporting_snapshot_id"
                )
        elif row["filename"]:
            raise SourceDataError(
                f"Citation-only source {source_id} must have a blank filename"
            )

    registry = {row["source_id"]: row for row in rows}
    for row in rows:
        if row["acquisition_method"] != "citation_only":
            continue
        source_id = row["source_id"]
        supporting_id = row["supporting_snapshot_id"]
        if not supporting_id:
            raise SourceDataError(
                f"Citation-only source {source_id} requires a "
                "supporting_snapshot_id"
            )
        supporting_source = registry.get(supporting_id)
        if supporting_source is None:
            raise SourceDataError(
                f"Citation-only source {source_id} references unknown "
                f"supporting_snapshot_id {supporting_id!r}"
            )
        if supporting_source["acquisition_method"] != "download":
            raise SourceDataError(
                f"Citation-only source {source_id} must reference a "
                "download source as supporting_snapshot_id"
            )
    return rows


def download_sources(
    sources_dir: Path | str,
    *,
    refresh: bool = False,
    client: httpx.Client | None = None,
) -> DownloadSummary:
    """Download snapshot sources and write a checksum manifest.

    Existing snapshots are reused by default.  This makes ordinary builds fast
    and preserves the exact legal evidence previously reviewed.  ``--refresh``
    is an explicit decision to replace those snapshots with current server
    content; the changed SHA-256 digest is then visible in the manifest.
    ``citation_only`` registry rows are retained for precise provenance but are
    never requested by this automated downloader.
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
        if not isinstance(prior, dict) or not isinstance(
            prior.get("sources", []), list
        ):
            raise SourceDataError(f"{manifest_path} has an invalid manifest structure")
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
            transport=httpx.HTTPTransport(retries=3),
            headers={
                "User-Agent": (
                    "awm-regression/0.4 "
                    "(academic reproducibility; source contact in repository)"
                )
            },
        )

    downloaded = 0
    cached = 0
    citation_only = 0
    entries: list[dict[str, object]] = []
    try:
        for source in registry:
            if source["acquisition_method"] == "citation_only":
                citation_only += 1
                continue
            target = _safe_target(sources_dir, source["filename"])
            fetched_at: str
            if target.exists() and not refresh:
                previous = prior_entries.get(source["source_id"])
                _validate_cached_snapshot(
                    target,
                    source["source_id"],
                    previous if isinstance(previous, dict) else None,
                )
                cached += 1
                fetched_at = str(
                    (previous.get("fetched_at") or "")
                    if isinstance(previous, dict)
                    else ""
                )
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
                _validate_download_content(target, response.content)
                _write_bytes_atomic(target, response.content)
                downloaded += 1
                fetched_at = datetime.now(UTC).isoformat()

            entries.append(
                {
                    "source_id": source["source_id"],
                    "source_url": source["source_url"],
                    "filename": source["filename"],
                    "acquisition_method": source["acquisition_method"],
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
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": entries,
    }
    _write_text_atomic(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return DownloadSummary(downloaded, cached, citation_only, manifest_path)


def validate_sources(sources_dir: Path | str) -> ValidationSummary:
    """Verify snapshots, citation-only support, and curated citations."""

    sources_dir = Path(sources_dir)
    registry_rows = _load_registry(sources_dir)
    registry = {row["source_id"]: row for row in registry_rows}
    manifest = _manifest_entries(sources_dir)
    downloadable_rows = [
        row
        for row in registry_rows
        if row["acquisition_method"] == "download"
    ]
    if downloadable_rows and not manifest:
        raise SourceDataError(
            f"No download manifest found in {sources_dir}; "
            "run `uv run awm-sources download`"
        )

    verified = 0
    for row in registry_rows:
        if row["acquisition_method"] == "citation_only":
            continue
        source_id = row["source_id"]
        target = _safe_target(sources_dir, row["filename"])
        if not target.exists():
            raise SourceDataError(
                f"Registered source snapshot is missing for {source_id}: {target}"
            )
        entry = manifest.get(source_id)
        if entry is None:
            raise SourceDataError(
                f"Download manifest has no entry for registered source {source_id}"
            )
        if entry.get("source_url") != row["source_url"]:
            raise SourceDataError(
                f"Manifest URL does not match registry for {source_id}; "
                "run `uv run awm-sources download --refresh`"
            )
        if entry.get("filename") != row["filename"]:
            raise SourceDataError(
                f"Manifest filename does not match registry for {source_id}; "
                "run `uv run awm-sources download --refresh`"
            )
        if entry.get("acquisition_method", "download") != "download":
            raise SourceDataError(
                f"Manifest acquisition method does not match registry for "
                f"{source_id}; run `uv run awm-sources download --refresh`"
            )
        _validate_cached_snapshot(target, source_id, entry)
        verified += 1

    curated_rows = 0
    for filename, required in _CURATED_SCHEMAS.items():
        path = sources_dir / "curated" / filename
        rows = _read_csv(path, required)
        for row in rows:
            _validate_source(row, path, registry)
            _validate_curated_row(filename, row, path)
        curated_rows += len(rows)

    participant_ids = {
        row["participant_id"]
        for row in _read_csv(
            sources_dir / "curated" / "cartel_periods.csv",
            _CURATED_SCHEMAS["cartel_periods.csv"],
        )
    }
    for row in _read_csv(
        sources_dir / "curated" / "contracts.csv",
        _CURATED_SCHEMAS["contracts.csv"],
    ):
        if (
            row.get("participant_id")
            and row["participant_id"] not in participant_ids
        ):
            path = sources_dir / "curated" / "contracts.csv"
            raise SourceDataError(
                f"{path}:{row['_line']}: unknown participant_id "
                f"{row['participant_id']!r}"
            )
    for relative_path, required in _SUPPORT_SCHEMAS.items():
        path = sources_dir / relative_path
        rows = _read_csv(path, required)
        for row in rows:
            _validate_source(row, path, registry)
            if relative_path.endswith("participant_aliases.csv"):
                if not row["alias"]:
                    raise SourceDataError(
                        f"{path}:{row['_line']}: alias cannot be blank"
                    )
                if row["participant_id"] not in participant_ids:
                    raise SourceDataError(
                        f"{path}:{row['_line']}: unknown participant_id "
                        f"{row['participant_id']!r}"
                    )
            elif row["review_status"] not in _FCC_REVIEW_STATUSES:
                raise SourceDataError(
                    f"{path}:{row['_line']}: review_status must be one of "
                    f"{', '.join(sorted(_FCC_REVIEW_STATUSES))}"
                )
            elif (
                row["review_status"] == "accepted"
                and not row.get("target_id", "").strip()
            ):
                raise SourceDataError(
                    f"{path}:{row['_line']}: an accepted FCC review row "
                    "requires target_id"
                )
        curated_rows += len(rows)

    return ValidationSummary(
        registered_sources=len(registry_rows),
        verified_downloads=verified,
        citation_only_sources=sum(
            row["acquisition_method"] == "citation_only"
            for row in registry_rows
        ),
        curated_rows=curated_rows,
    )


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


def _parse_source_bool(value: str, path: Path, row: Mapping[str, str]) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise SourceDataError(
        f"{path}:{row.get('_line', '?')}: expected a boolean, got {value!r}"
    )


def _validate_curated_row(
    filename: str, row: Mapping[str, str], path: Path
) -> None:
    """Validate researcher decisions that cannot be checked by CSV headers.

    Mechanical validation cannot establish that a legal interpretation is
    substantively correct.  It can, however, prevent a pending proceeding or
    an unreviewed procurement candidate from silently entering treatment.
    """

    if filename == "cartel_periods.csv":
        status = row["legal_status"]
        if status not in _LEGAL_STATUSES:
            raise SourceDataError(
                f"{path}:{row['_line']}: legal_status must be one of "
                f"{', '.join(sorted(_LEGAL_STATUSES))}"
            )
        eligible = _parse_source_bool(
            row["eligible_for_exposure"], path, row
        )
        if status != "final" and eligible:
            raise SourceDataError(
                f"{path}:{row['_line']}: a non-final participant period "
                "cannot be eligible_for_exposure"
            )
        prefixes = [
            prefix.strip()
            for prefix in row.get("gkz_prefixes", "").split("|")
            if prefix.strip()
        ]
        if len(prefixes) != len(set(prefixes)) or any(
            len(prefix) != 1 or prefix not in "123456789"
            for prefix in prefixes
        ):
            raise SourceDataError(
                f"{path}:{row['_line']}: gkz_prefixes must be unique "
                "one-digit state prefixes separated by |"
            )

    if filename == "contracts.csv":
        status = row["review_status"]
        if status not in _REVIEW_STATUSES:
            raise SourceDataError(
                f"{path}:{row['_line']}: review_status must be one of "
                f"{', '.join(sorted(_REVIEW_STATUSES))}"
            )
        if status == "accepted":
            missing = [
                field
                for field in (
                    "municipality_name",
                    "participant_id",
                    "contract_start",
                    "contract_end",
                    "reviewer",
                    "reviewed_at",
                )
                if not row.get(field, "").strip()
            ]
            if missing:
                raise SourceDataError(
                    f"{path}:{row['_line']}: accepted contract is missing "
                    f"{', '.join(missing)}"
                )
            try:
                date.fromisoformat(row["reviewed_at"])
            except ValueError as exc:
                raise SourceDataError(
                    f"{path}:{row['_line']}: reviewed_at must be YYYY-MM-DD"
                ) from exc


_ODS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_ODS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


def _ods_rows(
    ods_content: bytes, sheet_name: str, *, required: bool = True
) -> list[list[str]]:
    """Return text cells from one ODS sheet using only the standard library."""

    with ZipFile(io.BytesIO(ods_content)) as archive:
        try:
            root = ElementTree.fromstring(archive.read("content.xml"))
        except (KeyError, ElementTree.ParseError) as exc:
            raise SourceDataError("Administrative-change ODS is malformed") from exc

    table = next(
        (
            candidate
            for candidate in root.findall(f".//{{{_ODS_TABLE}}}table")
            if candidate.get(f"{{{_ODS_TABLE}}}name") == sheet_name
        ),
        None,
    )
    if table is None:
        if not required:
            return []
        raise SourceDataError(
            f"Administrative-change ODS lacks sheet {sheet_name!r}"
        )

    output: list[list[str]] = []
    for row in table.findall(f"{{{_ODS_TABLE}}}table-row"):
        row_repeat = int(
            row.get(f"{{{_ODS_TABLE}}}number-rows-repeated", "1")
        )
        values: list[str] = []
        for cell in row:
            if cell.tag not in {
                f"{{{_ODS_TABLE}}}table-cell",
                f"{{{_ODS_TABLE}}}covered-table-cell",
            }:
                continue
            column_repeat = int(
                cell.get(f"{{{_ODS_TABLE}}}number-columns-repeated", "1")
            )
            paragraphs = cell.findall(f".//{{{_ODS_TEXT}}}p")
            text = " ".join(
                "".join(paragraph.itertext()).strip()
                for paragraph in paragraphs
            ).strip()
            # Empty tail columns may be repeated tens of thousands of times.
            # They carry no data and need not be materialized.
            if text or column_repeat <= 64:
                values.extend([text] * column_repeat)
        if any(values):
            output.extend([values] * min(row_repeat, 1))
    return output


def _municipality_crosswalk_from_zip(
    path: Path,
    municipalities: Sequence[Mapping[str, str]],
    *,
    source_id: str,
    source_url: str,
    cutoff: date = date(2024, 1, 1),
) -> list[dict[str, str]]:
    """Map changed GKZ values deterministically into the selected universe.

    Statistics Austria's change table includes both one-to-one renumberings
    and genuine one-to-many divisions.  One-to-one chains can be normalized
    safely.  A split is retained as multiple rows with
    ``split_requires_review`` so no source row can be assigned to every
    successor by accident.
    """

    try:
        with ZipFile(path) as archive:
            ods_member = next(
                (
                    member
                    for member in archive.namelist()
                    if Path(member).name == "aenderungenGemeinden_ab2002.ods"
                ),
                None,
            )
            if ods_member is None:
                raise SourceDataError(
                    f"{path} lacks aenderungenGemeinden_ab2002.ods"
                )
            ods_content = archive.read(ods_member)
    except BadZipFile as exc:
        raise SourceDataError(
            f"Administrative-change source is not a valid ZIP: {path}"
        ) from exc

    rows = _ods_rows(ods_content, "alle_GKZaenderungen")
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row and row[0] == "Gemeindekennziffer alt"
        ),
        None,
    )
    if header_index is None:
        raise SourceDataError(
            "Administrative-change ODS lacks the expected GKZ header"
        )
    header = rows[header_index]
    required = {
        "Gemeindekennziffer alt",
        "Gemeinde alt",
        "Gemeindekennziffer neu",
        "Gemeinde neu",
        "in Kraft seit",
        "Änderungsgrund",
    }
    if missing := required - set(header):
        raise SourceDataError(
            "Administrative-change ODS is missing column(s): "
            + ", ".join(sorted(missing))
        )
    positions = {name: header.index(name) for name in required}

    edges: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    historical_names: defaultdict[str, set[str]] = defaultdict(set)
    for values in rows[header_index + 1 :]:
        if len(values) <= max(positions.values()):
            continue
        effective_text = values[positions["in Kraft seit"]].strip()
        try:
            effective = datetime.strptime(effective_text, "%d.%m.%Y").date()
        except ValueError as exc:
            raise SourceDataError(
                f"Invalid effective date in administrative-change ODS: "
                f"{effective_text!r}"
            ) from exc
        if effective > cutoff:
            continue
        old_gkz = values[positions["Gemeindekennziffer alt"]].strip().zfill(5)
        new_gkz = values[positions["Gemeindekennziffer neu"]].strip().zfill(5)
        old_name = values[positions["Gemeinde alt"]].strip()
        if not (
            len(old_gkz) == len(new_gkz) == 5
            and old_gkz.isdigit()
            and new_gkz.isdigit()
            and old_name
        ):
            raise SourceDataError(
                "Invalid GKZ/name row in administrative-change ODS"
            )
        historical_names[old_gkz].add(old_name)
        historical_names[new_gkz].add(
            values[positions["Gemeinde neu"]].strip()
        )
        edges[old_gkz].append(
            {
                "new_gkz": new_gkz,
                "effective": effective.isoformat(),
                "reason": values[positions["Änderungsgrund"]].strip(),
            }
        )

    current_names = {
        row["gkz"]: row["municipality_name"] for row in municipalities
    }
    current_gkz_by_name: defaultdict[str, set[str]] = defaultdict(set)
    for gkz, name in current_names.items():
        current_gkz_by_name[name].add(gkz)

    node_dates: defaultdict[str, set[str]] = defaultdict(set)
    node_reasons: defaultdict[str, set[str]] = defaultdict(set)
    rename_rows = _ods_rows(
        ods_content, "Namensaenderungen", required=False
    )
    rename_header_index = next(
        (
            index
            for index, row in enumerate(rename_rows)
            if row and row[0] == "Gemeindekennziffer"
        ),
        None,
    )
    if rename_header_index is not None:
        rename_header = rename_rows[rename_header_index]
        rename_positions = {
            name: rename_header.index(name)
            for name in (
                "Gemeindekennziffer",
                "Gemeindename alt",
                "Gemeindename neu",
                "in Kraft seit",
            )
        }
        for values in rename_rows[rename_header_index + 1 :]:
            if len(values) <= max(rename_positions.values()):
                continue
            effective_text = values[
                rename_positions["in Kraft seit"]
            ].strip()
            raw_gkz = values[
                rename_positions["Gemeindekennziffer"]
            ].strip()
            if not effective_text or not raw_gkz.isdigit():
                continue
            try:
                effective = datetime.strptime(
                    effective_text, "%d.%m.%Y"
                ).date()
            except ValueError as exc:
                raise SourceDataError(
                    "Invalid effective date in municipality-name change "
                    f"sheet: {effective_text!r}"
                ) from exc
            if effective > cutoff:
                continue
            gkz = raw_gkz.zfill(5)
            historical_names[gkz].update(
                {
                    values[rename_positions["Gemeindename alt"]].strip(),
                    values[rename_positions["Gemeindename neu"]].strip(),
                }
            )
            node_dates[gkz].add(effective.isoformat())
            node_reasons[gkz].add("Namensänderung")

    memo: dict[str, tuple[set[str], set[str], set[str]]] = {}

    def resolve(
        gkz: str, trail: tuple[str, ...] = ()
    ) -> tuple[set[str], set[str], set[str]]:
        if gkz in current_names:
            return {gkz}, set(), set()
        if gkz in memo:
            return memo[gkz]
        if gkz in trail:
            raise SourceDataError(
                "Cycle in Statistics Austria administrative-change table: "
                + " -> ".join((*trail, gkz))
            )
        targets: set[str] = set()
        dates: set[str] = set(node_dates[gkz])
        reasons: set[str] = set(node_reasons[gkz])
        for edge in edges.get(gkz, []):
            child_targets, child_dates, child_reasons = resolve(
                edge["new_gkz"], (*trail, gkz)
            )
            targets.update(child_targets)
            dates.update(child_dates)
            reasons.update(child_reasons)
            dates.add(edge["effective"])
            if edge["reason"]:
                reasons.add(edge["reason"])
        if not targets:
            for historical_name in historical_names.get(gkz, set()):
                targets.update(current_gkz_by_name.get(historical_name, set()))
        memo[gkz] = targets, dates, reasons
        return memo[gkz]

    output: list[dict[str, str]] = []
    historical_codes = set(edges) | {
        gkz for gkz in historical_names if gkz not in current_names
    }
    for old_gkz in sorted(historical_codes):
        targets, dates, reasons = resolve(old_gkz)
        if not targets:
            raise SourceDataError(
                f"Historical GKZ {old_gkz} does not resolve to the selected "
                f"{cutoff.year} municipality universe"
            )
        status = "automatic" if len(targets) == 1 else "split_requires_review"
        old_names = "|".join(sorted(historical_names[old_gkz]))
        for target in sorted(targets):
            output.append(
                {
                    "historical_gkz": old_gkz,
                    "historical_name": old_names,
                    "current_gkz": target,
                    "current_name": current_names[target],
                    "mapping_status": status,
                    "effective_dates": "|".join(sorted(dates)),
                    "change_reasons": "|".join(sorted(reasons)),
                    "source_id": source_id,
                    "source_url": source_url,
                }
            )
    return output


def _resolve_gkz(
    row: Mapping[str, str],
    path: Path,
    gkz_by_name: Mapping[str, Sequence[str]],
    municipality_names: Mapping[str, str],
    crosswalk_by_gkz: Mapping[str, Sequence[str]],
    gkz_by_historical_name: Mapping[str, Sequence[str]],
    historical_names_by_gkz: Mapping[str, Sequence[str]],
) -> str:
    supplied_gkz = row.get("gkz", "").strip()
    supplied_name = row.get("municipality_name", "").strip()
    if supplied_gkz:
        gkz = supplied_gkz.zfill(5)
        if gkz in municipality_names:
            candidates = [gkz]
            valid_names = [municipality_names[gkz]]
        else:
            candidates = list(crosswalk_by_gkz.get(gkz, ()))
            valid_names = list(historical_names_by_gkz.get(gkz, ()))
        if not candidates:
            raise SourceDataError(
                f"{path}:{row.get('_line', '?')}: unknown current or "
                f"historical GKZ {gkz}"
            )
        if len(candidates) > 1:
            raise SourceDataError(
                f"{path}:{row.get('_line', '?')}: historical GKZ {gkz} "
                "was split; supply the intended current gkz after reviewing "
                f"successors {', '.join(candidates)}"
            )
        if supplied_name and supplied_name not in valid_names:
            raise SourceDataError(
                f"{path}:{row.get('_line', '?')}: GKZ {gkz} does not match "
                f"municipality name {supplied_name!r}"
            )
        return candidates[0]
    candidates = gkz_by_name.get(supplied_name, ())
    if not candidates:
        candidates = gkz_by_historical_name.get(supplied_name, ())
    if not candidates:
        raise SourceDataError(
            f"{path}:{row.get('_line', '?')}: municipality name "
            f"{supplied_name!r} is not an exact match in the selected GKZ "
            "vintage or the official historical crosswalk"
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
    if not isinstance(payload, dict) or not isinstance(
        payload.get("sources", []), list
    ):
        raise SourceDataError(f"{path} has an invalid manifest structure")
    return {
        str(item["source_id"]): item
        for item in payload.get("sources", [])
        if isinstance(item, dict) and item.get("source_id")
    }


def build_raw_data(
    sources_dir: Path | str,
    raw_dir: Path | str,
    *,
    municipality_source_id: str = "statistik_austria_municipalities_2024",
    municipality_changes_source_id: str | None = None,
    municipality_reference_date: date = date(2024, 1, 1),
) -> RawBuildSummary:
    """Build normalized CSVs from downloaded and reviewed source records."""

    sources_dir = Path(sources_dir)
    raw_dir = Path(raw_dir)
    registry_rows = _load_registry(sources_dir)
    registry = {row["source_id"]: row for row in registry_rows}
    if municipality_source_id not in registry:
        raise SourceDataError(
            f"Municipality source_id is not registered: {municipality_source_id}"
        )
    municipality_source = registry[municipality_source_id]
    if municipality_source["acquisition_method"] != "download":
        raise SourceDataError(
            f"Municipality source_id must use acquisition_method=download: "
            f"{municipality_source_id}"
        )

    municipality_path = _safe_target(
        sources_dir, municipality_source["filename"]
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

    crosswalk: list[dict[str, str]] = []
    if municipality_changes_source_id is not None:
        if municipality_changes_source_id not in registry:
            raise SourceDataError(
                "Municipality-change source_id is not registered: "
                f"{municipality_changes_source_id}"
            )
        change_source = registry[municipality_changes_source_id]
        if change_source["acquisition_method"] != "download":
            raise SourceDataError(
                "Municipality-change source_id must use "
                "acquisition_method=download: "
                f"{municipality_changes_source_id}"
            )
        change_path = _safe_target(sources_dir, change_source["filename"])
        crosswalk = _municipality_crosswalk_from_zip(
            change_path,
            municipalities,
            source_id=municipality_changes_source_id,
            source_url=change_source["source_url"],
            cutoff=municipality_reference_date,
        )
    output["municipality_crosswalk.csv"] = crosswalk

    crosswalk_by_gkz: defaultdict[str, list[str]] = defaultdict(list)
    gkz_by_historical_name: defaultdict[str, list[str]] = defaultdict(list)
    historical_names_by_gkz: defaultdict[str, list[str]] = defaultdict(list)
    for crosswalk_row in crosswalk:
        old_gkz = crosswalk_row["historical_gkz"]
        current_gkz = crosswalk_row["current_gkz"]
        crosswalk_by_gkz[old_gkz].append(current_gkz)
        for historical_name in crosswalk_row["historical_name"].split("|"):
            if historical_name:
                historical_names_by_gkz[old_gkz].append(historical_name)
                gkz_by_historical_name[historical_name].append(current_gkz)
    crosswalk_by_gkz = defaultdict(
        list,
        {
            key: sorted(set(values))
            for key, values in crosswalk_by_gkz.items()
        },
    )
    gkz_by_historical_name = defaultdict(
        list,
        {
            key: sorted(set(values))
            for key, values in gkz_by_historical_name.items()
        },
    )
    historical_names_by_gkz = defaultdict(
        list,
        {
            key: sorted(set(values))
            for key, values in historical_names_by_gkz.items()
        },
    )

    curated_dir = sources_dir / "curated"

    for filename, required in _CURATED_SCHEMAS.items():
        path = curated_dir / filename
        rows = _read_csv(path, required)
        target_rows = output[filename]
        for row in rows:
            source_id = _validate_source(row, path, registry)
            _validate_curated_row(filename, row, path)
            if (
                filename == "contracts.csv"
                and row["review_status"] != "accepted"
            ):
                continue
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
                    row,
                    path,
                    gkz_by_name,
                    municipality_names,
                    crosswalk_by_gkz,
                    gkz_by_historical_name,
                    historical_names_by_gkz,
                )
            target_rows.append(normalized)

    raw_dir.mkdir(parents=True, exist_ok=True)
    for filename, fieldnames in RAW_SCHEMAS.items():
        rows = _deduplicate_and_sort(output[filename], fieldnames)
        _write_csv_atomic(raw_dir / filename, fieldnames, rows)

    # The raw source log makes a source_id resolvable without relying on a URL
    # that might later change.  A blank checksum either means `build` was run
    # before `download` or identifies a citation-only page that is deliberately
    # not fetched by automation.  The acquisition fields distinguish the two.
    manifest = _manifest_entries(sources_dir)
    source_log_rows = []
    for row in registry_rows:
        entry = (
            manifest.get(row["source_id"], {})
            if row["acquisition_method"] == "download"
            else {}
        )
        source_log_rows.append(
            {
                "source_id": row["source_id"],
                "source_url": row["source_url"],
                "local_path": row["filename"],
                "acquisition_method": row["acquisition_method"],
                "supporting_snapshot_id": row["supporting_snapshot_id"],
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
            "acquisition_method",
            "supporting_snapshot_id",
            "fetched_at",
            "sha256",
            "description",
        ],
        source_log_rows,
    )

    evidence_rows = sum(
        len(output[filename])
        for filename in RAW_SCHEMAS
        if filename
        not in {"municipalities.csv", "municipality_crosswalk.csv"}
    )
    return RawBuildSummary(
        len(municipalities), len(crosswalk), evidence_rows, raw_dir
    )
