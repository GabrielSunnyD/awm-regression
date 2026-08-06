from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import shapefile

from awm_exposure.pipeline import build_exposure
from awm_exposure.sources import (
    RAW_SCHEMAS,
    SourceDataError,
    build_raw_data,
    download_sources,
    validate_sources,
)


def write_csv(
    path: Path, fieldnames: list[str], rows: list[dict[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_municipality_zip(
    path: Path, municipalities: list[tuple[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary) / "municipalities"
        writer = shapefile.Writer(str(base), shapeType=shapefile.NULL)
        writer.field("ID", "C", size=5)
        writer.field("NAME", "C", size=100)
        for gkz, name in municipalities:
            writer.null()
            writer.record(gkz, name)
        writer.close()
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for suffix in (".shp", ".shx", ".dbf"):
                archive.write(base.with_suffix(suffix), f"municipalities{suffix}")


def write_admin_changes_zip(
    path: Path,
    changes: list[tuple[str, str, str, str, str, str]],
) -> None:
    rows = [
        (
            "Gemeindekennziffer alt",
            "Gemeinde alt",
            "Gemeindekennziffer neu",
            "Gemeinde neu",
            "in Kraft seit",
            "Änderungsgrund",
        ),
        *changes,
    ]
    xml_rows = []
    for row in rows:
        cells = "".join(
            "<table:table-cell office:value-type=\"string\">"
            f"<text:p>{value}</text:p></table:table-cell>"
            for value in row
        )
        xml_rows.append(f"<table:table-row>{cells}</table:table-row>")
    content = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<office:document-content "
        "xmlns:office=\"urn:oasis:names:tc:opendocument:xmlns:office:1.0\" "
        "xmlns:table=\"urn:oasis:names:tc:opendocument:xmlns:table:1.0\" "
        "xmlns:text=\"urn:oasis:names:tc:opendocument:xmlns:text:1.0\">"
        "<office:body><office:spreadsheet>"
        "<table:table table:name=\"alle_GKZaenderungen\">"
        + "".join(xml_rows)
        + "</table:table></office:spreadsheet></office:body>"
        "</office:document-content>"
    )
    ods_buffer = io.BytesIO()
    with ZipFile(ods_buffer, "w", ZIP_DEFLATED) as ods:
        ods.writestr("content.xml", content)
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "aenderungenGemeinden_ab2002.ods", ods_buffer.getvalue()
        )


class SourcePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.curated = self.sources / "curated"
        self.raw = self.root / "raw"

    def write_registry(
        self,
        filename: str = "downloads/municipalities.zip",
        *,
        include_changes: bool = False,
        include_citation_only: bool = False,
    ) -> None:
        rows = [
            {
                "source_id": "municipalities",
                "source_url": "https://example.test/municipalities.zip",
                "filename": filename,
                "acquisition_method": "download",
                "supporting_snapshot_id": "",
                "description": "Municipality test fixture",
            },
            {
                "source_id": "court",
                "source_url": "https://example.test/court.html",
                "filename": "downloads/court.html",
                "acquisition_method": "download",
                "supporting_snapshot_id": "",
                "description": "Court test fixture",
            },
            {
                "source_id": "members",
                "source_url": "https://example.test/members.html",
                "filename": "downloads/members.html",
                "acquisition_method": "download",
                "supporting_snapshot_id": "",
                "description": "Membership test fixture",
            },
        ]
        if include_changes:
            rows.append(
                {
                    "source_id": "changes",
                    "source_url": "https://example.test/changes.zip",
                    "filename": "downloads/changes.zip",
                    "acquisition_method": "download",
                    "supporting_snapshot_id": "",
                    "description": "Administrative changes fixture",
                }
            )
        if include_citation_only:
            rows.append(
                {
                    "source_id": "challenge_notice",
                    "source_url": "https://example.test/challenge.html",
                    "filename": "",
                    "acquisition_method": "citation_only",
                    "supporting_snapshot_id": "court",
                    "description": "Browser-reviewed citation fixture",
                }
            )
        write_csv(
            self.sources / "registry.csv",
            [
                "source_id",
                "source_url",
                "filename",
                "acquisition_method",
                "supporting_snapshot_id",
                "description",
            ],
            rows,
        )

    def write_curated(self, municipality_name: str = "Alpha") -> None:
        write_csv(
            self.curated / "direct_evidence.csv",
            [
                "gkz",
                "municipality_name",
                "exposed",
                "exposure_start",
                "exposure_end",
                "source_id",
                "source_url",
                "notes",
            ],
            [
                {
                    "gkz": "",
                    "municipality_name": municipality_name,
                    "exposed": "1",
                    "exposure_start": "2019",
                    "exposure_end": "2019",
                    "source_id": "court",
                    "notes": "Reviewed court finding",
                }
            ],
        )
        write_csv(
            self.curated / "cartel_periods.csv",
            [
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
            [
                {
                    "participant_id": "firm",
                    "participant_name": "Firm",
                    "cartel_start": "2003",
                    "cartel_end": "2021-03",
                    "legal_status": "final",
                    "eligible_for_exposure": "1",
                    "gkz_prefixes": "",
                    "source_id": "court",
                }
            ],
        )
        write_csv(
            self.curated / "contracts.csv",
            [
                "candidate_id",
                "review_status",
                "municipality_name",
                "gkz",
                "participant_id",
                "contract_start",
                "contract_end",
                "source_id",
                "source_url",
                "reviewer",
                "reviewed_at",
                "notes",
            ],
            [],
        )
        write_csv(
            self.curated / "association_exposure.csv",
            [
                "association_id",
                "association_name",
                "exposed",
                "exposure_start",
                "exposure_end",
                "source_id",
                "source_url",
                "notes",
            ],
            [
                {
                    "association_id": "assoc",
                    "association_name": "Association",
                    "exposed": "1",
                    "exposure_start": "2019",
                    "exposure_end": "2020",
                    "source_id": "court",
                }
            ],
        )
        write_csv(
            self.curated / "participant_aliases.csv",
            ["participant_id", "alias", "source_id", "notes"],
            [
                {
                    "participant_id": "firm",
                    "alias": "Firm Ltd",
                    "source_id": "court",
                }
            ],
        )
        write_csv(
            self.sources / "review" / "fcc_public_project_review.csv",
            [
                "source_year",
                "project_name",
                "review_status",
                "disposition",
                "target_id",
                "source_id",
            ],
            [
                {
                    "source_year": "2019",
                    "project_name": "Alpha",
                    "review_status": "accepted",
                    "disposition": "direct_evidence",
                    "target_id": "Alpha",
                    "source_id": "court",
                }
            ],
        )
        write_csv(
            self.curated / "association_memberships.csv",
            [
                "municipality_name",
                "association_id",
                "membership_start",
                "membership_end",
                "source_id",
                "source_url",
                "notes",
            ],
            [
                {
                    "municipality_name": "Beta",
                    "association_id": "assoc",
                    "membership_start": "2018",
                    "membership_end": "",
                    "source_id": "members",
                }
            ],
        )

    def test_builds_every_raw_schema_and_resolves_names_to_gkz(self) -> None:
        self.write_registry()
        write_municipality_zip(
            self.sources / "downloads/municipalities.zip",
            [
                ("10002", "Beta"),
                ("10001", "Alpha"),
                ("90101", "Wien-Innere Stadt"),
                ("90201", "Wien-Leopoldstadt"),
            ],
        )
        self.write_curated()

        summary = build_raw_data(
            self.sources,
            self.raw,
            municipality_source_id="municipalities",
        )

        self.assertEqual(summary.municipalities, 3)
        self.assertEqual(summary.crosswalk_rows, 0)
        self.assertEqual(summary.evidence_rows, 4)
        for filename, fields in RAW_SCHEMAS.items():
            self.assertTrue((self.raw / filename).exists())
            with (self.raw / filename).open(encoding="utf-8") as handle:
                self.assertEqual(next(csv.reader(handle)), fields)
        self.assertEqual(
            read_csv(self.raw / "municipalities.csv"),
            [
                {"gkz": "10001", "municipality_name": "Alpha"},
                {"gkz": "10002", "municipality_name": "Beta"},
                {"gkz": "90001", "municipality_name": "Wien"},
            ],
        )
        self.assertEqual(
            read_csv(self.raw / "direct_evidence.csv")[0]["gkz"], "10001"
        )
        membership = read_csv(self.raw / "association_memberships.csv")[0]
        self.assertEqual(membership["gkz"], "10002")
        self.assertEqual(
            membership["source_url"], "https://example.test/members.html"
        )
        source_log = read_csv(self.raw / "source_log.csv")
        self.assertEqual(len(source_log), 3)
        self.assertTrue(all(row["sha256"] == "" for row in source_log))

        panel_summary = build_exposure(
            self.raw,
            self.root / "processed",
            start_year=2019,
            end_year=2020,
        )
        panel = {
            (row["gkz"], row["year"]): row
            for row in read_csv(panel_summary.main_output)
        }
        self.assertEqual(panel_summary.rows, 6)
        self.assertEqual(panel[("10001", "2019")]["exposure"], "1")
        self.assertEqual(panel[("10001", "2020")]["data_found"], "false")
        self.assertEqual(panel[("10002", "2019")]["exposure"], "1")
        self.assertEqual(panel[("10002", "2020")]["exposure"], "1")

    def test_unknown_municipality_name_fails_instead_of_fuzzy_matching(self) -> None:
        self.write_registry()
        write_municipality_zip(
            self.sources / "downloads/municipalities.zip",
            [("10001", "Alpha"), ("10002", "Beta")],
        )
        self.write_curated(municipality_name="Alfa")

        with self.assertRaisesRegex(SourceDataError, "not an exact match"):
            build_raw_data(
                self.sources,
                self.raw,
                municipality_source_id="municipalities",
            )

    def test_download_cache_refresh_and_checksum_manifest(self) -> None:
        self.write_registry(filename="downloads/municipalities.zip")
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if request.url.path.endswith(".zip"):
                content = b"PK\x03\x04source bytes"
            else:
                content = b"<!doctype html><html><body>source bytes</body></html>"
            return httpx.Response(200, request=request, content=content)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            first = download_sources(self.sources, client=client)
            second = download_sources(self.sources, client=client)
            third = download_sources(self.sources, refresh=True, client=client)

        self.assertEqual((first.downloaded, first.cached), (3, 0))
        self.assertEqual((second.downloaded, second.cached), (0, 3))
        self.assertEqual((third.downloaded, third.cached), (3, 0))
        self.assertEqual(first.citation_only, 0)
        self.assertEqual(len(calls), 6)
        manifest = json.loads(
            (self.sources / "download_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(manifest["sources"]), 3)
        self.assertTrue(
            all(len(source["sha256"]) == 64 for source in manifest["sources"])
        )
        self.assertTrue(
            all(
                source["acquisition_method"] == "download"
                for source in manifest["sources"]
            )
        )
        self.write_curated()
        validation = validate_sources(self.sources)
        self.assertEqual(validation.registered_sources, 3)
        self.assertEqual(validation.verified_downloads, 3)
        self.assertEqual(validation.citation_only_sources, 0)

        (self.sources / "downloads/court.html").write_text(
            "<html>tampered</html>", encoding="utf-8"
        )
        with self.assertRaisesRegex(SourceDataError, "(size|checksum) changed"):
            validate_sources(self.sources)

    def test_citation_only_sources_are_skipped_but_remain_valid_citations(
        self,
    ) -> None:
        self.write_registry(include_citation_only=True)
        self.write_curated()
        direct = read_csv(self.curated / "direct_evidence.csv")
        direct[0]["source_id"] = "challenge_notice"
        write_csv(
            self.curated / "direct_evidence.csv",
            list(direct[0]),
            direct,
        )
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if request.url.path.endswith("challenge.html"):
                self.fail("citation-only URL must not be requested")
            if request.url.path.endswith(".zip"):
                content = b"PK\x03\x04source bytes"
            else:
                content = b"<!doctype html><html><body>source bytes</body></html>"
            return httpx.Response(200, request=request, content=content)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            summary = download_sources(self.sources, client=client)

        self.assertEqual(
            (summary.downloaded, summary.cached, summary.citation_only),
            (3, 0, 1),
        )
        self.assertEqual(len(calls), 3)
        manifest = json.loads(
            (self.sources / "download_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["schema_version"], 2)
        self.assertNotIn(
            "challenge_notice",
            {source["source_id"] for source in manifest["sources"]},
        )
        validation = validate_sources(self.sources)
        self.assertEqual(validation.registered_sources, 4)
        self.assertEqual(validation.verified_downloads, 3)
        self.assertEqual(validation.citation_only_sources, 1)

        registry = read_csv(self.sources / "registry.csv")
        registry[-1]["supporting_snapshot_id"] = "missing"
        write_csv(
            self.sources / "registry.csv",
            list(registry[0]),
            registry,
        )
        with self.assertRaisesRegex(SourceDataError, "unknown supporting_snapshot_id"):
            validate_sources(self.sources)

    def test_registry_rejects_path_traversal(self) -> None:
        self.write_registry(filename="../outside.zip")
        with self.assertRaisesRegex(SourceDataError, "escapes"):
            download_sources(self.sources)

    def test_historical_gkz_crosswalk_resolves_chains_and_rejects_splits(
        self,
    ) -> None:
        self.write_registry(include_changes=True)
        write_municipality_zip(
            self.sources / "downloads/municipalities.zip",
            [("10001", "Alpha New"), ("10002", "Beta")],
        )
        write_admin_changes_zip(
            self.sources / "downloads/changes.zip",
            [
                (
                    "09001",
                    "Old Alpha",
                    "09501",
                    "Middle Alpha",
                    "01.01.2010",
                    "Renumbering",
                ),
                (
                    "09501",
                    "Middle Alpha",
                    "10001",
                    "Alpha New",
                    "01.01.2015",
                    "Merger",
                ),
                (
                    "08001",
                    "Split Place",
                    "10001",
                    "Alpha New",
                    "01.01.2020",
                    "Division",
                ),
                (
                    "08001",
                    "Split Place",
                    "10002",
                    "Beta",
                    "01.01.2020",
                    "Division",
                ),
            ],
        )
        self.write_curated(municipality_name="Old Alpha")
        direct = read_csv(self.curated / "direct_evidence.csv")
        direct[0]["gkz"] = "09001"
        write_csv(
            self.curated / "direct_evidence.csv",
            list(direct[0]),
            direct,
        )

        summary = build_raw_data(
            self.sources,
            self.raw,
            municipality_source_id="municipalities",
            municipality_changes_source_id="changes",
        )
        self.assertEqual(summary.crosswalk_rows, 4)
        self.assertEqual(
            read_csv(self.raw / "direct_evidence.csv")[0]["gkz"], "10001"
        )
        crosswalk = read_csv(self.raw / "municipality_crosswalk.csv")
        self.assertEqual(
            {
                row["current_gkz"]
                for row in crosswalk
                if row["historical_gkz"] == "08001"
            },
            {"10001", "10002"},
        )
        self.assertTrue(
            all(
                row["mapping_status"] == "split_requires_review"
                for row in crosswalk
                if row["historical_gkz"] == "08001"
            )
        )

        direct[0]["gkz"] = "08001"
        direct[0]["municipality_name"] = "Split Place"
        write_csv(
            self.curated / "direct_evidence.csv",
            list(direct[0]),
            direct,
        )
        with self.assertRaisesRegex(SourceDataError, "was split"):
            build_raw_data(
                self.sources,
                self.raw,
                municipality_source_id="municipalities",
                municipality_changes_source_id="changes",
            )

    def test_only_manually_accepted_contracts_enter_raw_inputs(self) -> None:
        self.write_registry()
        write_municipality_zip(
            self.sources / "downloads/municipalities.zip",
            [("10001", "Alpha"), ("10002", "Beta")],
        )
        self.write_curated()
        fields = [
            "candidate_id",
            "review_status",
            "municipality_name",
            "gkz",
            "participant_id",
            "contract_start",
            "contract_end",
            "source_id",
            "source_url",
            "reviewer",
            "reviewed_at",
            "notes",
        ]
        write_csv(
            self.curated / "contracts.csv",
            fields,
            [
                {
                    "candidate_id": "ted:accepted",
                    "review_status": "accepted",
                    "municipality_name": "Alpha",
                    "participant_id": "firm",
                    "contract_start": "2018",
                    "contract_end": "2020",
                    "source_id": "court",
                    "reviewer": "Researcher",
                    "reviewed_at": "2026-07-30",
                },
                {
                    "candidate_id": "ted:pending",
                    "review_status": "pending",
                    "municipality_name": "Beta",
                    "participant_id": "firm",
                    "contract_start": "2018",
                    "contract_end": "2020",
                    "source_id": "court",
                },
            ],
        )

        build_raw_data(
            self.sources,
            self.raw,
            municipality_source_id="municipalities",
        )
        contracts = read_csv(self.raw / "contracts.csv")
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0]["gkz"], "10001")


if __name__ == "__main__":
    unittest.main()
