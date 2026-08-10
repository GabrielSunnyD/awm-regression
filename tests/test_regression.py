from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from awm_exposure.regression import RegressionInputError, run_regression


def write_csv(
    path: Path, fieldnames: list[str], rows: list[dict[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class RegressionPipelineTests(unittest.TestCase):
    def make_exact_panel(
        self, root: Path, *, include_data_found: bool = True
    ) -> tuple[Path, Path, Path]:
        years = list(range(2010, 2016))
        exposure_rows: list[dict[str, object]] = []
        expenditure_rows: list[dict[str, object]] = []
        control_rows: list[dict[str, object]] = []

        for municipality_index in range(8):
            gkz = f"{101 + municipality_index:05d}"
            expenditure_row: dict[str, object] = {
                # Confirm that codes whose leading zeroes were lost still join.
                "gkz": str(101 + municipality_index),
            }
            for year_index, year in enumerate(years):
                exposed = int(
                    (
                        2 * municipality_index
                        + 3 * year_index
                        + municipality_index * year_index
                    )
                    % 5
                    < 2
                )
                control = (
                    ((municipality_index + 1) * (year_index + 2)) % 11
                    + 0.1 * municipality_index
                    - 0.2 * year_index
                )
                expenditure = (
                    500
                    + 25 * municipality_index
                    + 7 * year_index
                    + 3.0 * exposed
                    - 0.75 * control
                )
                exposure_row: dict[str, object] = {
                    "gkz": gkz,
                    "year": year,
                    "exposure": exposed,
                }
                if include_data_found:
                    exposure_row["data_found"] = not (
                        municipality_index == 0 and year_index == 1
                    )
                exposure_rows.append(exposure_row)
                expenditure_row[str(year)] = expenditure
                control_rows.append(
                    {"gkz": gkz, "year": year, "population": control}
                )
            expenditure_rows.append(expenditure_row)

        exposure_path = root / "exposure.csv"
        expenditure_path = root / "expenditure.csv"
        controls_path = root / "controls.csv"
        exposure_fields = ["gkz", "year", "exposure"]
        if include_data_found:
            exposure_fields.append("data_found")
        write_csv(exposure_path, exposure_fields, exposure_rows)
        write_csv(
            expenditure_path,
            ["gkz", *(str(year) for year in years)],
            expenditure_rows,
        )
        write_csv(
            controls_path,
            ["gkz", "year", "population"],
            control_rows,
        )
        return exposure_path, expenditure_path, controls_path

    def test_estimates_two_way_fixed_effect_model_and_writes_audit_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, expenditure, controls = self.make_exact_panel(root)

            summary = run_regression(
                exposure,
                expenditure,
                root / "output",
                controls_csv=controls,
                cluster="none",
            )

            self.assertEqual(summary.observations, 47)
            self.assertEqual(summary.municipalities, 8)
            self.assertEqual(summary.years, 6)
            self.assertEqual(summary.controls, ("population",))
            self.assertAlmostEqual(summary.exposure_estimate, 3.0, places=9)
            self.assertAlmostEqual(summary.within_r_squared, 1.0, places=10)

            results = {row["term"]: row for row in read_csv(summary.results_output)}
            self.assertEqual(set(results), {"exposure", "population"})
            self.assertAlmostEqual(float(results["exposure"]["estimate"]), 3.0)
            self.assertAlmostEqual(float(results["population"]["estimate"]), -0.75)

            sample_keys = {
                (row["gkz"], int(row["year"]))
                for row in read_csv(summary.sample_output)
            }
            self.assertNotIn(("00101", 2011), sample_keys)
            self.assertIn(("00101", 2010), sample_keys)

            metadata = json.loads(summary.metadata_output.read_text(encoding="utf-8"))
            self.assertEqual(
                metadata["model"]["formula"],
                "expenditure ~ exposure + population | gkz + year",
            )
            self.assertEqual(
                metadata["sample"]["drop_counts"]["unknown_exposure"], 1
            )
            self.assertEqual(metadata["estimation"]["residual_degrees_of_freedom"], 32)

    def test_missing_data_found_requires_explicit_unknown_exposure_opt_in(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, expenditure, controls = self.make_exact_panel(
                root, include_data_found=False
            )
            with self.assertRaisesRegex(RegressionInputError, "no data_found column"):
                run_regression(
                    exposure,
                    expenditure,
                    root / "rejected",
                    controls_csv=controls,
                )

            summary = run_regression(
                exposure,
                expenditure,
                root / "accepted",
                controls_csv=controls,
                include_unknown_exposure=True,
                cluster="none",
            )
            self.assertEqual(summary.observations, 48)
            self.assertAlmostEqual(summary.exposure_estimate, 3.0, places=9)

    def test_gkz_and_two_way_clustered_inference_are_finite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, expenditure, controls = self.make_exact_panel(root)
            rows = read_csv(expenditure)
            years = list(range(2010, 2016))
            for municipality_index, row in enumerate(rows):
                for year_index, year in enumerate(years):
                    noise = 0.4 * (
                        (
                            7 * municipality_index
                            + 5 * year_index
                            + municipality_index * year_index
                        )
                        % 13
                        - 6
                    )
                    row[str(year)] = float(row[str(year)]) + noise
            write_csv(
                expenditure,
                ["gkz", *(str(year) for year in years)],
                rows,
            )

            for cluster in ("gkz", "gkz-year"):
                with self.subTest(cluster=cluster):
                    summary = run_regression(
                        exposure,
                        expenditure,
                        root / cluster,
                        controls_csv=controls,
                        cluster=cluster,
                    )
                    self.assertGreater(summary.exposure_standard_error, 0)
                    results = {
                        row["term"]: row
                        for row in read_csv(summary.results_output)
                    }
                    self.assertNotEqual(results["exposure"]["p_value"], "")
                    metadata = json.loads(
                        summary.metadata_output.read_text(encoding="utf-8")
                    )
                    self.assertEqual(
                        metadata["model"]["standard_errors"], cluster
                    )

    def test_controls_csv_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, expenditure, _ = self.make_exact_panel(root)
            summary = run_regression(
                exposure,
                expenditure,
                root / "output",
                cluster="none",
            )
            self.assertEqual(summary.controls, ())
            self.assertEqual(
                [row["term"] for row in read_csv(summary.results_output)],
                ["exposure"],
            )

    def test_missing_complete_cases_and_singletons_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, expenditure, controls = self.make_exact_panel(root)
            rows = read_csv(controls)
            for row in rows:
                if row["gkz"] == "00108" and row["year"] != "2010":
                    row["population"] = ""
            write_csv(controls, ["gkz", "year", "population"], rows)

            summary = run_regression(
                exposure,
                expenditure,
                root / "output",
                controls_csv=controls,
                cluster="none",
            )
            metadata = json.loads(summary.metadata_output.read_text(encoding="utf-8"))
            drops = metadata["sample"]["drop_counts"]
            self.assertEqual(drops["missing_controls"], 5)
            self.assertEqual(drops["singleton_fixed_effect"], 1)
            self.assertEqual(summary.municipalities, 7)

    def test_rejects_rank_deficient_controls_after_fixed_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, expenditure, controls = self.make_exact_panel(root)
            rows = read_csv(controls)
            for row in rows:
                row["population"] = "1"
            write_csv(controls, ["gkz", "year", "population"], rows)

            with self.assertRaisesRegex(RegressionInputError, "rank deficient"):
                run_regression(
                    exposure,
                    expenditure,
                    root / "output",
                    controls_csv=controls,
                )

    def test_rejects_nonpositive_log_outcome_and_invalid_wide_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, expenditure, controls = self.make_exact_panel(root)
            rows = read_csv(expenditure)
            rows[0]["2010"] = "0"
            write_csv(
                expenditure,
                ["gkz", *(str(year) for year in range(2010, 2016))],
                rows,
            )
            with self.assertRaisesRegex(RegressionInputError, "strictly positive"):
                run_regression(
                    exposure,
                    expenditure,
                    root / "log-output",
                    controls_csv=controls,
                    log_outcome=True,
                )

            bad_expenditure = root / "bad-expenditure.csv"
            write_csv(
                bad_expenditure,
                ["gkz", "municipality_name", "2010"],
                [{"gkz": "00101", "municipality_name": "Example", "2010": 1}],
            )
            with self.assertRaisesRegex(RegressionInputError, "non-year"):
                run_regression(
                    exposure,
                    bad_expenditure,
                    root / "bad-output",
                    controls_csv=controls,
                )

    def test_rejects_positive_exposure_marked_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, expenditure, controls = self.make_exact_panel(root)
            rows = read_csv(exposure)
            rows[0]["data_found"] = "false"
            self.assertEqual(rows[0]["exposure"], "1")
            write_csv(
                exposure,
                ["gkz", "year", "exposure", "data_found"],
                rows,
            )
            with self.assertRaisesRegex(
                RegressionInputError, "exposure=1 cannot have data_found=false"
            ):
                run_regression(
                    exposure,
                    expenditure,
                    root / "output",
                    controls_csv=controls,
                )


if __name__ == "__main__":
    unittest.main()
