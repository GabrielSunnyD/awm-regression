# Austrian waste-cartel municipality-year exposure

This project builds an auditable Austrian municipality-year panel:

```text
gkz,year,exposure,data_found
```

The default output crosses every municipality in Statistics Austria's
2024-01-01 GKZ universe with 2001–2024: 2,093 municipalities × 24 years =
50,232 rows.

For municipality \(i\) and year \(t\), `exposure=1` when at least one reviewed
source supports:

1. direct municipality evidence overlapping \(t\);
2. an accepted municipality–supplier contract overlapping both \(t\) and that
   participant's eligible final infringement period; or
3. dated association membership overlapping both \(t\) and a reviewed
   association-exposure interval.

All interval tests require at least one shared calendar day. Exposure is never
carried into another year merely because a municipality was exposed once.

## Build the panel

Install [`uv`](https://docs.astral.sh/uv/), clone the repository, and run:

```bash
uv sync --locked
uv run awm-build
```

`awm-build` downloads or reuses registered official snapshots, validates the
source layer, constructs the historical-GKZ crosswalk and normalized inputs,
then builds:

- `data/processed/municipality_year_exposure.csv`;
- `data/processed/municipality_year_exposure_audit.csv`.

Useful variants are:

```bash
uv run awm-build --offline
uv run awm-build --refresh
uv run awm-exposure --start-year 2001 --end-year 2024
```

`--offline` requires an existing checksum-verified cache. `--refresh`
intentionally replaces every registered snapshot. The stages can be inspected
separately:

```bash
uv run awm-sources download
uv run awm-sources validate
uv run awm-sources build
uv run awm-exposure
```

## Find procurement candidates

TED discovery is a separate, review-only workflow:

```bash
uv run awm-ted
```

It queries the unauthenticated TED Search API for Austrian waste-service
notices, matches reported winners against source-backed participant aliases,
and writes `data/review/procurement_candidates.csv`. Every generated row is
`pending`; it cannot change exposure.

To accept a candidate, a researcher must verify the municipal buyer, award,
service relevance, supplier, and performance dates; register and download the
underlying notice; and add an `accepted` row with reviewer and review date to
`data/sources/curated/contracts.csv`. Pending and rejected rows are excluded
from `data/raw/contracts.csv` by construction.

## Evidence architecture

| Layer | Role |
|---|---|
| `data/sources/registry.csv` | Official URLs and stable source IDs |
| `data/sources/downloads/` | Cached source snapshots |
| `data/sources/download_manifest.json` | Access time, byte size, and SHA-256 |
| `data/sources/curated/*.csv` | Reviewed propositions and participant aliases |
| `data/sources/review/*.csv` | Decisions about ambiguous court-table entries |
| `data/review/` | Generated procurement candidates awaiting review |
| `data/raw/*.csv` | Generated, normalized classifier inputs and crosswalk |
| `data/processed/*.csv` | Final panel and rule-level audit |

The generated normalized tables are:

| File | Role |
|---|---|
| `municipalities.csv` | Fixed 2024 GKZ universe |
| `municipality_crosswalk.csv` | Official historical-to-2024 GKZ mappings |
| `direct_evidence.csv` | Dated municipality findings |
| `cartel_periods.csv` | Participant period, legal status, eligibility, and region |
| `contracts.csv` | Manually accepted municipality–supplier contracts |
| `association_exposure.csv` | Dated association findings |
| `association_memberships.csv` | Dated municipal membership intervals |

The source parser uses exact municipality names and stable participant or
association IDs. It never labels every place-name hit in a legal document:
addresses, private customers, facilities, districts, and comparison locations
are not automatically municipality exposure.

## Legal-status and territorial safeguards

The default participant roster includes the finalized FCC, Huber,
Saubermacher/Trügler/pink robin, Killer, and KAB findings. Energie AG
Oberösterreich Umwelt Service is recorded as `pending_admitted` but
`eligible_for_exposure=0`; it cannot trigger treatment unless methodology and
source coding are deliberately changed after a final disposition.

Participant periods also retain supported Austrian state prefixes. A contract
outside a participant's coded geographic scope does not trigger the contract
rule. A contract still sets `data_found=true` for its performance years,
because the municipality-year was evaluated.

The FCC project-table review inventory records every municipality- or
association-like entry considered during extraction as `accepted`, `pending`,
or `excluded`. Broad district references, private customers, wastewater, and
facilities with unresolved service scope remain outside treatment.

## `data_found` and current coverage

`data_found` is municipality-year specific:

| exposure | data_found | Interpretation |
|---:|:---:|---|
| 1 | true | At least one annual rule is positive |
| 0 | true | Evidence covers the year but no positive rule is met |
| 0 | false | No coded evidence covers the municipality-year; zero is a default |
| 1 | false | Impossible by construction |

Default zeroes are unknown coverage, not confirmed clean controls. Public court
project lists are illustrative rather than exhaustive.

The current official-source build contains:

- 50,232 balanced panel rows;
- 650 historical crosswalk rows;
- 77 normalized evidence rows;
- 130 exposed municipality-years; and
- 130 municipality-years with `data_found=true`.

The expansion is driven mainly by dated legal membership records for all 19
GABL and 15 AWS Schwechat members at the corresponding FCC project years.
`contracts.csv` remains empty because no procurement candidate has yet passed
manual acceptance.

## Territorial interpretation

The output remains a fixed-2024-geography panel. Statistics Austria's
machine-readable administrative-change archive now resolves deterministic
renumbering and merger chains since 2002 automatically. A genuine one-to-many
split is written as `split_requires_review` and causes evidence normalization
to fail until the researcher supplies the intended 2024 successor.

This crosswalk improves source resolution; it does not claim that every 2024
municipality existed unchanged in every earlier year. A contemporaneous-
boundary panel is a different estimand requiring annual universes and explicit
allocation rules for split municipalities.

## Test

```bash
uv lock --check
uv run python -m compileall -q src scripts
uv run python -m unittest discover -s tests -v
```

Tests cover the balanced panel, day-level interval intersection, all three
exposure paths, legal-status and geographic gates, source checksums, exact
municipality resolution, automatic historical chains, split rejection,
contract-review gating, and paginated TED candidate generation.

See [`docs/data_sources.md`](docs/data_sources.md) for the ingestion runbook and
[`docs/methodology.md`](docs/methodology.md) for the classification and
identification choices.
