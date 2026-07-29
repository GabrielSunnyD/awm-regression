from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from awm_exposure.pipeline import InputError, build_exposure


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


class ExposurePipelineTests(unittest.TestCase):
    def test_builds_dated_panel_for_all_three_rules_and_unknown_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            outputs = root / "processed"

            write_csv(
                inputs / "municipalities.csv",
                ["gkz", "municipality_name"],
                [
                    {"gkz": "10101", "municipality_name": "Direct"},
                    {"gkz": "10102", "municipality_name": "Contract"},
                    {"gkz": "10103", "municipality_name": "Reviewed zero"},
                    {"gkz": "10104", "municipality_name": "Association"},
                    {"gkz": "10105", "municipality_name": "Non-cartel supplier"},
                    {"gkz": "10106", "municipality_name": "No data"},
                ],
            )
            write_csv(
                inputs / "direct_evidence.csv",
                [
                    "gkz",
                    "exposed",
                    "exposure_start",
                    "exposure_end",
                    "source_id",
                ],
                [
                    {
                        "gkz": "10101",
                        "exposed": "1",
                        "exposure_start": "2004",
                        "exposure_end": "2004",
                        "source_id": "court-1",
                    }
                ],
            )
            write_csv(
                inputs / "cartel_periods.csv",
                [
                    "participant_id",
                    "cartel_start",
                    "cartel_end",
                    "source_id",
                ],
                [
                    {
                        "participant_id": "firm-a",
                        "cartel_start": "2002-07",
                        "cartel_end": "2021-03-31",
                        "source_id": "decision-a",
                    }
                ],
            )
            write_csv(
                inputs / "contracts.csv",
                [
                    "gkz",
                    "participant_id",
                    "contract_start",
                    "contract_end",
                    "source_id",
                ],
                [
                    {
                        "gkz": "10102",
                        "participant_id": "firm-a",
                        "contract_start": "2005",
                        "contract_end": "2010",
                        "source_id": "award-1",
                    },
                    {
                        "gkz": "10103",
                        "participant_id": "firm-a",
                        "contract_start": "2022",
                        "contract_end": "2023",
                        "source_id": "award-2",
                    },
                    {
                        "gkz": "10105",
                        "participant_id": "other-firm",
                        "contract_start": "2010",
                        "contract_end": "2011",
                        "source_id": "award-3",
                    },
                ],
            )
            write_csv(
                inputs / "association_exposure.csv",
                [
                    "association_id",
                    "exposed",
                    "exposure_start",
                    "exposure_end",
                    "source_id",
                ],
                [
                    {
                        "association_id": "assoc-a",
                        "exposed": "true",
                        "exposure_start": "2004",
                        "exposure_end": "2015",
                        "source_id": "assoc-decision",
                    }
                ],
            )
            write_csv(
                inputs / "association_memberships.csv",
                [
                    "gkz",
                    "association_id",
                    "membership_start",
                    "membership_end",
                    "source_id",
                ],
                [
                    {
                        "gkz": "10104",
                        "association_id": "assoc-a",
                        "membership_start": "2007",
                        "membership_end": "",
                        "source_id": "member-list",
                    }
                ],
            )

            summary = build_exposure(
                inputs, outputs, start_year=2004, end_year=2023
            )
            self.assertEqual(summary.municipalities, 6)
            self.assertEqual(summary.years, 20)
            self.assertEqual(summary.rows, 120)
            self.assertEqual(summary.exposed_rows, 16)
            self.assertEqual(summary.ever_exposed_municipalities, 3)
            self.assertEqual(summary.with_data_rows, 20)

            main = {
                (row["gkz"], row["year"]): row
                for row in read_csv(summary.main_output)
            }
            self.assertEqual(
                main[("10101", "2004")],
                {
                    "gkz": "10101",
                    "year": "2004",
                    "exposure": "1",
                    "data_found": "true",
                },
            )
            self.assertEqual(main[("10101", "2005")]["data_found"], "false")
            self.assertEqual(main[("10102", "2005")]["exposure"], "1")
            self.assertEqual(main[("10102", "2011")]["data_found"], "false")
            self.assertEqual(
                main[("10103", "2022")],
                {
                    "gkz": "10103",
                    "year": "2022",
                    "exposure": "0",
                    "data_found": "true",
                },
            )
            self.assertEqual(main[("10104", "2006")]["exposure"], "0")
            self.assertEqual(main[("10104", "2007")]["exposure"], "1")
            self.assertEqual(main[("10104", "2016")]["data_found"], "false")
            self.assertEqual(main[("10106", "2010")]["data_found"], "false")

            audit = {
                (row["gkz"], row["year"]): row
                for row in read_csv(summary.audit_output)
            }
            self.assertEqual(
                audit[("10102", "2005")]["exposure_reasons"], "contract"
            )
            self.assertEqual(
                audit[("10102", "2005")]["positive_source_ids"],
                "award-1|decision-a",
            )
            self.assertEqual(
                audit[("10104", "2007")]["exposure_reasons"], "association"
            )

    def test_same_calendar_year_without_same_day_overlap_is_not_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            write_csv(
                inputs / "municipalities.csv",
                ["gkz"],
                [{"gkz": "10101"}],
            )
            write_csv(
                inputs / "cartel_periods.csv",
                ["participant_id", "cartel_start", "cartel_end"],
                [
                    {
                        "participant_id": "firm-a",
                        "cartel_start": "2021-01-01",
                        "cartel_end": "2021-03-31",
                    }
                ],
            )
            write_csv(
                inputs / "contracts.csv",
                ["gkz", "participant_id", "contract_start", "contract_end"],
                [
                    {
                        "gkz": "10101",
                        "participant_id": "firm-a",
                        "contract_start": "2021-04-01",
                        "contract_end": "2021-12-31",
                    }
                ],
            )

            summary = build_exposure(
                inputs, root / "processed", start_year=2021, end_year=2021
            )
            self.assertEqual(
                read_csv(summary.main_output)[0],
                {
                    "gkz": "10101",
                    "year": "2021",
                    "exposure": "0",
                    "data_found": "true",
                },
            )

    def test_missing_optional_files_produce_balanced_default_zeroes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            write_csv(
                inputs / "municipalities.csv",
                ["gkz"],
                [{"gkz": "101"}, {"gkz": "10102"}],
            )

            summary = build_exposure(
                inputs,
                root / "processed",
                start_year=2001,
                end_year=2002,
                include_data_found=False,
                write_audit=False,
            )
            self.assertEqual(
                read_csv(summary.main_output),
                [
                    {"gkz": "00101", "year": "2001", "exposure": "0"},
                    {"gkz": "00101", "year": "2002", "exposure": "0"},
                    {"gkz": "10102", "year": "2001", "exposure": "0"},
                    {"gkz": "10102", "year": "2002", "exposure": "0"},
                ],
            )
            self.assertEqual(summary.rows, 4)
            self.assertIsNone(summary.audit_output)

    def test_default_panel_range_is_2001_through_2024(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            write_csv(
                inputs / "municipalities.csv",
                ["gkz"],
                [{"gkz": "10101"}],
            )

            summary = build_exposure(
                inputs,
                root / "processed",
                write_audit=False,
            )
            rows = read_csv(summary.main_output)
            self.assertEqual(summary.years, 24)
            self.assertEqual(summary.rows, 24)
            self.assertEqual(rows[0]["year"], "2001")
            self.assertEqual(rows[-1]["year"], "2024")

    def test_unknown_evidence_gkz_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            write_csv(
                inputs / "municipalities.csv",
                ["gkz"],
                [{"gkz": "10101"}],
            )
            write_csv(
                inputs / "direct_evidence.csv",
                ["gkz", "exposed", "exposure_start", "exposure_end"],
                [
                    {
                        "gkz": "99999",
                        "exposed": "1",
                        "exposure_start": "2010",
                        "exposure_end": "2010",
                    }
                ],
            )

            with self.assertRaisesRegex(
                InputError, "harmonized territorial reference year"
            ):
                build_exposure(inputs, root / "processed")

    def test_invalid_boolean_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            write_csv(
                inputs / "municipalities.csv",
                ["gkz"],
                [{"gkz": "10101"}],
            )
            write_csv(
                inputs / "direct_evidence.csv",
                ["gkz", "exposed", "exposure_start", "exposure_end"],
                [
                    {
                        "gkz": "10101",
                        "exposed": "maybe",
                        "exposure_start": "2010",
                        "exposure_end": "2010",
                    }
                ],
            )

            with self.assertRaisesRegex(InputError, "expected a boolean"):
                build_exposure(inputs, root / "processed")

    def test_undated_evidence_fails_instead_of_applying_to_every_year(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            write_csv(
                inputs / "municipalities.csv",
                ["gkz"],
                [{"gkz": "10101"}],
            )
            write_csv(
                inputs / "direct_evidence.csv",
                ["gkz", "exposed", "exposure_start", "exposure_end"],
                [
                    {
                        "gkz": "10101",
                        "exposed": "1",
                        "exposure_start": "",
                        "exposure_end": "",
                    }
                ],
            )

            with self.assertRaisesRegex(InputError, "at least one of"):
                build_exposure(inputs, root / "processed")

    def test_invalid_panel_range_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            write_csv(
                inputs / "municipalities.csv",
                ["gkz"],
                [{"gkz": "10101"}],
            )
            with self.assertRaisesRegex(InputError, "start_year"):
                build_exposure(
                    inputs,
                    root / "processed",
                    start_year=2024,
                    end_year=2001,
                )


if __name__ == "__main__":
    unittest.main()
