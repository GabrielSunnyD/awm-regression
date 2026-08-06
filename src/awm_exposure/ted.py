"""Generate a review-only procurement queue from the public TED Search API.

TED notices are useful discovery records, but they are not automatically
municipality contracts.  Buyer names can be associations, notices can be
amendments rather than awards, and publication dates are not necessarily
performance dates.  This module therefore matches reviewed participant aliases
to reported winners and writes *pending candidates*.  Nothing here is consumed
by the exposure classifier.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import httpx


TED_API_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_FIELDS = [
    "publication-number",
    "publication-date",
    "procedure-identifier",
    "buyer-name",
    "winner-name",
    "classification-cpv",
    "title-proc",
    "contract-conclusion-date",
    "contract-duration-start-date-lot",
    "contract-duration-end-date-lot",
]
TED_CANDIDATE_FIELDS = [
    "candidate_id",
    "review_status",
    "municipality_name",
    "gkz",
    "participant_id",
    "matched_alias",
    "contract_start",
    "contract_end",
    "source_id",
    "source_url",
    "reviewer",
    "reviewed_at",
    "publication_number",
    "publication_date",
    "procedure_identifier",
    "buyer_name",
    "winner_name",
    "title",
    "cpv_codes",
    "contract_conclusion_date",
    "notes",
]


class TedDataError(ValueError):
    """Raised when TED input or output cannot be interpreted safely."""


@dataclass(frozen=True)
class TedSummary:
    notices_examined: int
    candidates: int
    pages: int
    output_path: Path
    metadata_path: Path


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


def _write_csv_atomic(
    path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, str]]
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
    _write_bytes_atomic(path, output.getvalue().encode("utf-8"))


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", " ", value).strip()


def _text_values(value: object) -> list[str]:
    """Flatten TED's multilingual/list-valued fields deterministically."""

    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Mapping):
        output: list[str] = []
        for key in sorted(value):
            output.extend(_text_values(value[key]))
        return output
    if isinstance(value, Sequence):
        output = []
        for item in value:
            output.extend(_text_values(item))
        return output
    return [str(value)]


def _joined(value: object) -> str:
    return "|".join(sorted(set(_text_values(value))))


def load_participant_aliases(path: Path | str) -> list[dict[str, str]]:
    """Load source-backed participant aliases used only for candidate matching."""

    path = Path(path)
    if not path.exists():
        raise TedDataError(f"Participant alias file is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"participant_id", "alias"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise TedDataError(
                f"{path} must contain participant_id and alias columns"
            )
        output: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for line_number, row in enumerate(reader, start=2):
            participant_id = (row.get("participant_id") or "").strip()
            alias = (row.get("alias") or "").strip()
            normalized = _normalize_text(alias)
            if not participant_id or not normalized:
                raise TedDataError(
                    f"{path}:{line_number}: participant_id and alias "
                    "cannot be blank"
                )
            key = participant_id, normalized
            if key in seen:
                continue
            seen.add(key)
            output.append(
                {
                    "participant_id": participant_id,
                    "alias": alias,
                    "normalized_alias": normalized,
                }
            )
    if not output:
        raise TedDataError(f"{path} contains no participant aliases")
    return output


def _matches(winner_name: str, aliases: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    normalized_winner = f" {_normalize_text(winner_name)} "
    matches = []
    for alias in aliases:
        normalized_alias = alias["normalized_alias"]
        if f" {normalized_alias} " in normalized_winner:
            matches.append(dict(alias))
    return matches


def _ted_query(start_year: int, end_year: int) -> str:
    if not (1 <= start_year <= end_year <= 9999):
        raise TedDataError("TED years must be ordered and between 1 and 9999")
    # CPV 90500000 is hierarchical in TED expert search and therefore captures
    # waste-related child codes such as collection and disposal services.
    return (
        "buyer-country = AUT AND classification-cpv = 90500000 "
        f"AND publication-date >= {start_year:04d}0101 "
        f"AND publication-date <= {end_year:04d}1231"
    )


def download_ted_candidates(
    aliases_path: Path | str,
    output_path: Path | str,
    *,
    start_year: int = 2001,
    end_year: int = 2024,
    api_url: str = TED_API_URL,
    page_size: int = 250,
    client: httpx.Client | None = None,
) -> TedSummary:
    """Query TED and write participant-matched records as pending candidates."""

    if not (1 <= page_size <= 250):
        raise TedDataError("TED page_size must be between 1 and 250")
    aliases = load_participant_aliases(aliases_path)
    query = _ted_query(start_year, end_year)
    output_path = Path(output_path)

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(90.0),
            transport=httpx.HTTPTransport(retries=3),
            headers={
                "User-Agent": (
                    "awm-regression/0.4 "
                    "(academic procurement candidate generation)"
                )
            },
        )

    notices_examined = 0
    page = 1
    pages = 0
    candidates: dict[str, dict[str, str]] = {}
    try:
        while True:
            payload = {
                "query": query,
                "fields": TED_FIELDS,
                "page": page,
                "limit": page_size,
                "scope": "ALL",
                "paginationMode": "PAGE_NUMBER",
                "onlyLatestVersions": True,
            }
            try:
                response = client.post(api_url, json=payload)
                response.raise_for_status()
                result = response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                raise TedDataError(
                    f"TED search request failed on page {page}: {exc}"
                ) from exc
            if not isinstance(result, dict) or not isinstance(
                result.get("notices"), list
            ):
                raise TedDataError(
                    f"TED search returned an invalid response on page {page}"
                )
            notices = result["notices"]
            pages += 1
            notices_examined += len(notices)

            for notice in notices:
                if not isinstance(notice, dict):
                    raise TedDataError("TED search returned a non-object notice")
                publication_number = _joined(
                    notice.get("publication-number")
                )
                winner_name = _joined(notice.get("winner-name"))
                if not publication_number or not winner_name:
                    continue
                for match in _matches(winner_name, aliases):
                    candidate_id = (
                        f"ted:{publication_number}:{match['participant_id']}"
                    )
                    candidates[candidate_id] = {
                        "candidate_id": candidate_id,
                        "review_status": "pending",
                        "municipality_name": "",
                        "gkz": "",
                        "participant_id": match["participant_id"],
                        "matched_alias": match["alias"],
                        "contract_start": _joined(
                            notice.get("contract-duration-start-date-lot")
                        ),
                        "contract_end": _joined(
                            notice.get("contract-duration-end-date-lot")
                        ),
                        "source_id": "",
                        "source_url": (
                            "https://ted.europa.eu/en/notice/"
                            f"{publication_number}/html"
                        ),
                        "reviewer": "",
                        "reviewed_at": "",
                        "publication_number": publication_number,
                        "publication_date": _joined(
                            notice.get("publication-date")
                        ),
                        "procedure_identifier": _joined(
                            notice.get("procedure-identifier")
                        ),
                        "buyer_name": _joined(notice.get("buyer-name")),
                        "winner_name": winner_name,
                        "title": _joined(notice.get("title-proc")),
                        "cpv_codes": _joined(
                            notice.get("classification-cpv")
                        ),
                        "contract_conclusion_date": _joined(
                            notice.get("contract-conclusion-date")
                        ),
                        "notes": (
                            "Automated alias match only; verify the buyer is a "
                            "municipality, this is an award, and the performance "
                            "interval before accepting."
                        ),
                    }

            total = result.get("totalNoticeCount")
            if not notices:
                break
            if isinstance(total, int) and page * page_size >= total:
                break
            if len(notices) < page_size:
                break
            page += 1
    finally:
        if owns_client:
            client.close()

    candidate_rows = [candidates[key] for key in sorted(candidates)]
    _write_csv_atomic(output_path, TED_CANDIDATE_FIELDS, candidate_rows)
    metadata_path = output_path.with_name(
        f"{output_path.stem}_metadata.json"
    )
    metadata = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "api_url": api_url,
        "query": query,
        "fields": TED_FIELDS,
        "notices_examined": notices_examined,
        "candidates": len(candidate_rows),
        "pages": pages,
        "warning": (
            "Candidate generation is not exposure coding. Only manually "
            "accepted, source-registered contract rows enter data/raw."
        ),
    }
    _write_bytes_atomic(
        metadata_path,
        (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    return TedSummary(
        notices_examined,
        len(candidate_rows),
        pages,
        output_path,
        metadata_path,
    )
