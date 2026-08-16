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
    def test_loads_canonical_panel_and_selects_direct_specification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
            rows = read_csv(exposure)
            for row in rows:
                row["exposure_direct"] = row["exposure"]
                row["exposure_regional"] = "0"
                row["exposure_basis"] = (
                    "direct:municipality" if row["exposure"] == "1" else ""
                )
                row["data_found_direct"] = row["data_found"]
                row["data_found_regional"] = "false"
            write_csv(
                exposure,
                [
                    "gkz", "year", "exposure_direct", "exposure_regional",
                    "exposure", "exposure_basis", "data_found",
                    "data_found_direct", "data_found_regional",
                ],
                rows,
            )
            summary = run_regression(
                exposure,
                input_csv,
                root / "output",
                cluster="none",
                exposure_column="exposure_direct",
            )
            self.assertAlmostEqual(summary.exposure_estimate, 3.0, places=9)

            rows[0]["exposure"] = str(1 - int(rows[0]["exposure_direct"]))
            write_csv(
                exposure,
                [
                    "gkz", "year", "exposure_direct", "exposure_regional",
                    "exposure", "exposure_basis", "data_found",
                    "data_found_direct", "data_found_regional",
                ],
                rows,
            )
            with self.assertRaisesRegex(RegressionInputError, "must equal max"):
                run_regression(
                    exposure,
                    input_csv,
                    root / "invalid-output",
                    exposure_column="exposure_direct",
                )

    def make_exact_panel(
        self,
        root: Path,
        *,
        include_data_found: bool = True,
        include_controls: bool = True,
    ) -> tuple[Path, Path]:
        years = list(range(2010, 2016))
        exposure_rows: list[dict[str, object]] = []
        input_rows: list[dict[str, object]] = []

        for municipality_index in range(8):
            gkz = f"{101 + municipality_index:05d}"
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
                input_row: dict[str, object] = {
                    # Confirm that codes whose leading zeroes were lost still join.
                    "gkz": str(101 + municipality_index),
                    "year": year,
                    "expenditure": expenditure,
                }
                if include_controls:
                    input_row["population"] = control
                input_rows.append(input_row)

        exposure_path = root / "exposure.csv"
        input_path = root / "regression-input.csv"
        exposure_fields = ["gkz", "year", "exposure"]
        if include_data_found:
            exposure_fields.append("data_found")
        write_csv(exposure_path, exposure_fields, exposure_rows)
        write_csv(
            input_path,
            ["gkz", "year", "expenditure"]
            + (["population"] if include_controls else []),
            input_rows,
        )
        return exposure_path, input_path

    def test_estimates_two_way_fixed_effect_model_and_writes_audit_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)

            summary = run_regression(
                exposure,
                input_csv,
                root / "output",
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
            self.assertEqual(metadata["schema_version"], 2)
            self.assertEqual(metadata["inputs"]["input_csv"], str(input_csv))
            self.assertNotIn("expenditure_csv", metadata["inputs"])
            self.assertNotIn("controls_csv", metadata["inputs"])
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
            exposure, input_csv = self.make_exact_panel(
                root, include_data_found=False
            )
            with self.assertRaisesRegex(RegressionInputError, "no data_found column"):
                run_regression(
                    exposure,
                    input_csv,
                    root / "rejected",
                )

            summary = run_regression(
                exposure,
                input_csv,
                root / "accepted",
                include_unknown_exposure=True,
                cluster="none",
            )
            self.assertEqual(summary.observations, 48)
            self.assertAlmostEqual(summary.exposure_estimate, 3.0, places=9)

    def test_gkz_and_two_way_clustered_inference_are_finite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
            rows = read_csv(input_csv)
            for row in rows:
                municipality_index = int(row["gkz"]) - 101
                year_index = int(row["year"]) - 2010
                noise = 0.4 * (
                    (
                        7 * municipality_index
                        + 5 * year_index
                        + municipality_index * year_index
                    )
                    % 13
                    - 6
                )
                row["expenditure"] = float(row["expenditure"]) + noise
            write_csv(
                input_csv,
                ["gkz", "year", "expenditure", "population"],
                rows,
            )

            for cluster in ("gkz", "gkz-year"):
                with self.subTest(cluster=cluster):
                    summary = run_regression(
                        exposure,
                        input_csv,
                        root / cluster,
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

    def test_control_columns_are_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(
                root, include_controls=False
            )
            summary = run_regression(
                exposure,
                input_csv,
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
            exposure, input_csv = self.make_exact_panel(root)
            rows = read_csv(input_csv)
            for row in rows:
                if row["gkz"] == "108" and row["year"] != "2010":
                    row["population"] = ""
            write_csv(
                input_csv,
                ["gkz", "year", "expenditure", "population"],
                rows,
            )

            summary = run_regression(
                exposure,
                input_csv,
                root / "output",
                cluster="none",
            )
            metadata = json.loads(summary.metadata_output.read_text(encoding="utf-8"))
            drops = metadata["sample"]["drop_counts"]
            self.assertEqual(drops["missing_controls"], 5)
            self.assertEqual(drops["singleton_fixed_effect"], 1)
            self.assertEqual(summary.municipalities, 7)

    def test_names_time_invariant_control_absorbed_by_fixed_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
            rows = read_csv(input_csv)
            for row in rows:
                row["stable_population"] = row["gkz"]
            write_csv(
                input_csv,
                [
                    "gkz", "year", "expenditure", "population",
                    "stable_population",
                ],
                rows,
            )

            with self.assertRaises(RegressionInputError) as caught:
                run_regression(
                    exposure,
                    input_csv,
                    root / "output",
                )
            message = str(caught.exception)
            self.assertIn("individually absorbed", message)
            self.assertIn("stable_population", message)

    def test_names_both_duplicated_controls_as_jointly_collinear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
            rows = read_csv(input_csv)
            for row in rows:
                row["population_copy"] = row["population"]
            write_csv(
                input_csv,
                ["gkz", "year", "expenditure", "population", "population_copy"],
                rows,
            )

            with self.assertRaises(RegressionInputError) as caught:
                run_regression(exposure, input_csv, root / "output")
            message = str(caught.exception)
            self.assertIn("jointly collinear", message)
            self.assertIn("population", message)
            self.assertIn("population_copy", message)

    def test_names_exposure_and_control_when_they_are_collinear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
            exposure_by_key = {
                (row["gkz"].lstrip("0"), row["year"]): row["exposure"]
                for row in read_csv(exposure)
            }
            rows = read_csv(input_csv)
            for row in rows:
                row["exposure_proxy"] = exposure_by_key[(row["gkz"], row["year"])]
            write_csv(
                input_csv,
                ["gkz", "year", "expenditure", "population", "exposure_proxy"],
                rows,
            )

            with self.assertRaises(RegressionInputError) as caught:
                run_regression(exposure, input_csv, root / "output")
            message = str(caught.exception)
            self.assertIn("jointly collinear", message)
            self.assertIn("exposure", message)
            self.assertIn("exposure_proxy", message)

    def test_names_selected_exposure_absorbed_by_fixed_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
            rows = read_csv(exposure)
            for row in rows:
                value = int(row["gkz"][-1]) % 2
                row.update(
                    exposure_direct=value,
                    exposure_regional=0,
                    exposure=value,
                    data_found_direct="true",
                    data_found_regional="true",
                    data_found="true",
                )
            fields = [
                "gkz", "year", "exposure_direct", "exposure_regional",
                "exposure", "data_found", "data_found_direct",
                "data_found_regional",
            ]
            write_csv(exposure, fields, rows)

            with self.assertRaises(RegressionInputError) as caught:
                run_regression(
                    exposure,
                    input_csv,
                    root / "output",
                    exposure_column="exposure_direct",
                )
            message = str(caught.exception)
            self.assertIn("individually absorbed", message)
            self.assertIn("exposure_direct", message)

    def test_rejects_nonpositive_log_outcome_and_missing_expenditure_column(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
            rows = read_csv(input_csv)
            rows[0]["expenditure"] = "0"
            write_csv(
                input_csv,
                ["gkz", "year", "expenditure", "population"],
                rows,
            )
            with self.assertRaisesRegex(RegressionInputError, "strictly positive"):
                run_regression(
                    exposure,
                    input_csv,
                    root / "log-output",
                    log_outcome=True,
                )

            bad_input = root / "bad-input.csv"
            write_csv(
                bad_input,
                ["gkz", "year", "population"],
                [{"gkz": "00101", "year": 2010, "population": 1000}],
            )
            with self.assertRaisesRegex(RegressionInputError, "expenditure"):
                run_regression(
                    exposure,
                    bad_input,
                    root / "bad-output",
                )

    def test_blank_values_are_dropped_but_numeric_zeroes_are_kept(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
            rows = read_csv(input_csv)
            for row in rows:
                key = (row["gkz"], row["year"])
                if key == ("101", "2010"):
                    row["expenditure"] = "0"
                    row["population"] = "0"
                elif key == ("102", "2010"):
                    row["expenditure"] = ""
                elif key == ("103", "2010"):
                    row["population"] = ""
            write_csv(
                input_csv,
                ["gkz", "year", "expenditure", "population"],
                rows,
            )

            summary = run_regression(
                exposure,
                input_csv,
                root / "output",
                cluster="none",
            )
            sample = {
                (row["gkz"], row["year"]): row
                for row in read_csv(summary.sample_output)
            }
            self.assertEqual(sample[("00101", "2010")]["expenditure"], "0")
            self.assertEqual(sample[("00101", "2010")]["population"], "0")
            self.assertNotIn(("00102", "2010"), sample)
            self.assertNotIn(("00103", "2010"), sample)

            metadata = json.loads(summary.metadata_output.read_text(encoding="utf-8"))
            drops = metadata["sample"]["drop_counts"]
            self.assertEqual(drops["missing_expenditure"], 1)
            self.assertEqual(drops["missing_controls"], 1)

    def test_rejects_positive_exposure_marked_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exposure, input_csv = self.make_exact_panel(root)
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
                    input_csv,
                    root / "output",
                )


if __name__ == "__main__":
    unittest.main()
