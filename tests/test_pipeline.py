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
    def test_all_three_rules_and_default_zero(self) -> None:
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
                ["gkz", "exposed", "source_id"],
                [{"gkz": "10101", "exposed": "1", "source_id": "court-1"}],
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

            summary = build_exposure(inputs, outputs)
            self.assertEqual(summary.municipalities, 6)
            self.assertEqual(summary.exposed, 3)
            self.assertEqual(summary.with_data, 5)

            main = {row["gkz"]: row for row in read_csv(summary.main_output)}
            self.assertEqual(main["10101"], {
                "gkz": "10101", "exposure": "1", "data_found": "true"
            })
            self.assertEqual(main["10102"]["exposure"], "1")
            self.assertEqual(main["10103"], {
                "gkz": "10103", "exposure": "0", "data_found": "true"
            })
            self.assertEqual(main["10104"]["exposure"], "1")
            self.assertEqual(main["10105"]["data_found"], "true")
            self.assertEqual(main["10106"], {
                "gkz": "10106", "exposure": "0", "data_found": "false"
            })

            audit = {
                row["gkz"]: row for row in read_csv(summary.audit_output)
            }
            self.assertEqual(audit["10102"]["exposure_reasons"], "contract")
            self.assertEqual(
                audit["10102"]["positive_source_ids"], "award-1|decision-a"
            )
            self.assertEqual(
                audit["10104"]["exposure_reasons"], "association"
            )

    def test_missing_optional_files_produces_default_zeroes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "raw"
            write_csv(
                inputs / "municipalities.csv",
                ["gkz"],
                [{"gkz": "101"}, {"gkz": "10102"}],
            )

            summary = build_exposure(
                inputs, root / "processed", include_data_found=False, write_audit=False
            )
            rows = read_csv(summary.main_output)
            self.assertEqual(
                rows,
                [
                    {"gkz": "00101", "exposure": "0"},
                    {"gkz": "10102", "exposure": "0"},
                ],
            )
            self.assertIsNone(summary.audit_output)

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
                ["gkz", "exposed"],
                [{"gkz": "99999", "exposed": "1"}],
            )

            with self.assertRaisesRegex(InputError, "territorial reference date"):
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
                ["gkz", "exposed"],
                [{"gkz": "10101", "exposed": "maybe"}],
            )

            with self.assertRaisesRegex(InputError, "expected a boolean"):
                build_exposure(inputs, root / "processed")


if __name__ == "__main__":
    unittest.main()


