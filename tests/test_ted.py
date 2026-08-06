from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from awm_exposure.ted import TedDataError, download_ted_candidates


def write_csv(
    path: Path, fieldnames: list[str], rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class TedCandidateTests(unittest.TestCase):
    def test_paginates_flattens_and_writes_pending_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            aliases = root / "aliases.csv"
            output = root / "procurement_candidates.csv"
            write_csv(
                aliases,
                ["participant_id", "alias"],
                [
                    {
                        "participant_id": "fcc",
                        "alias": "FCC Austria Abfall Service AG",
                    },
                    {
                        "participant_id": "saubermacher",
                        "alias": "Trügler Recycling und Transport GesmbH",
                    },
                ],
            )
            requested_pages: list[int] = []

            def handler(request: httpx.Request) -> httpx.Response:
                payload = json.loads(request.content)
                requested_pages.append(payload["page"])
                common = {
                    "totalNoticeCount": 3,
                    "iterationNextToken": None,
                    "timedOut": False,
                }
                if payload["page"] == 1:
                    notices = [
                        {
                            "publication-number": "100-2020",
                            "publication-date": "2020-01-02+01:00",
                            "buyer-name": {"deu": ["Gemeinde Alpha"]},
                            "winner-name": {
                                "deu": ["FCC Austria Abfall Service AG"]
                            },
                            "title-proc": {"deu": ["Abfallsammlung"]},
                            "classification-cpv": ["90511000"],
                            "contract-duration-start-date-lot": [
                                "2020-04-01"
                            ],
                            "contract-duration-end-date-lot": [
                                "2023-03-31"
                            ],
                        },
                        {
                            "publication-number": "101-2020",
                            "winner-name": {"deu": ["Unrelated GmbH"]},
                        },
                    ]
                else:
                    notices = [
                        {
                            "publication-number": "200-2021",
                            "publication-date": "2021-02-03+01:00",
                            "buyer-name": {"deu": ["Verband Beta"]},
                            "winner-name": {
                                "deu": [
                                    "Trügler Recycling und Transport GesmbH"
                                ]
                            },
                            "classification-cpv": ["90500000"],
                        }
                    ]
                return httpx.Response(
                    200,
                    request=request,
                    json={**common, "notices": notices},
                )

            with httpx.Client(
                transport=httpx.MockTransport(handler)
            ) as client:
                summary = download_ted_candidates(
                    aliases,
                    output,
                    start_year=2001,
                    end_year=2024,
                    page_size=2,
                    client=client,
                )

            self.assertEqual(requested_pages, [1, 2])
            self.assertEqual(summary.notices_examined, 3)
            self.assertEqual(summary.candidates, 2)
            rows = read_csv(output)
            self.assertTrue(
                all(row["review_status"] == "pending" for row in rows)
            )
            fcc = next(row for row in rows if row["participant_id"] == "fcc")
            self.assertEqual(fcc["buyer_name"], "Gemeinde Alpha")
            self.assertEqual(fcc["contract_start"], "2020-04-01")
            self.assertEqual(
                fcc["source_url"],
                "https://ted.europa.eu/en/notice/100-2020/html",
            )
            metadata = json.loads(
                summary.metadata_path.read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["candidates"], 2)
            self.assertIn("buyer-country = AUT", metadata["query"])

    def test_rejects_invalid_page_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            aliases = root / "aliases.csv"
            write_csv(
                aliases,
                ["participant_id", "alias"],
                [{"participant_id": "firm", "alias": "Firm GmbH"}],
            )
            with self.assertRaisesRegex(TedDataError, "page_size"):
                download_ted_candidates(
                    aliases,
                    root / "out.csv",
                    page_size=251,
                )


if __name__ == "__main__":
    unittest.main()
