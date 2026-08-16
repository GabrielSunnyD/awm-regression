# Austrian waste-cartel municipality-year exposure

This project builds an auditable Austrian municipality-year panel in long
form:

```text
gkz,year,exposure_direct,exposure_regional,exposure,exposure_basis,data_found,...
```

The default output crosses every municipality in Statistics Austria's
2024-01-01 GKZ universe with 2001–2024: 2,093 municipalities × 24 years =
50,232 rows.

It also writes a wide exposure matrix with one row per municipality and one
column per year:

```text
gkz,municipality_name,2001,...,2024
```

`exposure_direct` is the union of the first three narrow rules below;
`exposure_regional` is the fourth preliminary rule; and `exposure` is their
maximum:

1. direct municipality evidence overlapping \(t\);
2. an accepted municipality–supplier contract overlapping both \(t\) and that
   participant's eligible final infringement period; or
3. dated association membership overlapping both \(t\) and a reviewed
   association-exposure interval; or
4. the municipality's state overlapping a final, eligible, source-backed
   regional cartel-operation interval.

The fourth channel is deliberately broad but time-limited. A dated FCC project
exposes every 2024-geography GKZ in the project's Bundesland only for the
documented year or consecutive documented years. It is never extended over
FCC's entire infringement period from one isolated project. The accepted rules
currently cover specific years in Carinthia, Lower Austria, Salzburg, and
Styria; the other five states remain unverified. They do **not** infer scope
from an address or facility and do not claim that every coded municipality was
a customer or suffered damage.

All interval tests require at least one shared calendar day. Exposure is never
carried into another year merely because a municipality was exposed once.
Because the documented cartel periods end in March 2021, every full calendar
year from 2022 onward is coded as a known non-exposed post-raid period for all
municipalities. The mixed 2021 calendar year is not assigned this rule.

## Build the panel

Install [`uv`](https://docs.astral.sh/uv/), clone the repository, and run:

```bash
uv sync --locked
uv run awm-build
```

`awm-build` downloads or reuses registered official snapshots, skips URLs
explicitly marked `citation_only`, validates both acquisition paths, constructs
the historical-GKZ crosswalk and normalized inputs, then builds:

- `data/processed/municipality_year_exposure.csv`;
- `data/processed/municipality_year_exposure_wide.csv`;
- `data/processed/municipality_year_exposure_audit.csv`; and
- `data/processed/municipality_year_exposure_diagnostics.csv`.

The wide file is an exposure-only convenience view. Use the long file when an
analysis must distinguish evidence-supported zeroes from default zeroes with
`data_found`.

The long panel also carries `data_found_direct` and `data_found_regional` so a
direct-only regression does not treat a regional-only finding as proof of a
clean direct zero (and vice versa). `data_found` is the combined-specification
coverage flag retained for backward compatibility.

Useful variants are:

```bash
uv run awm-build --offline
uv run awm-build --refresh
uv run awm-exposure --start-year 2001 --end-year 2024
```

`--offline` requires an existing checksum-verified cache for every `download`
source. `--refresh` intentionally replaces those snapshots; it never requests
`citation_only` URLs. The stages can be inspected separately:

```bash
uv run awm-sources download
uv run awm-sources validate
uv run awm-sources build
uv run awm-exposure
```

## Estimate the expenditure effect

The regression layer joins the long exposure panel to one researcher-supplied
long CSV, then estimates expenditure on exposure and controls with GKZ and year
fixed effects:

```bash
uv run awm-regress \
  --exposure-column exposure \
  --input-csv path/to/regression_input.csv
```

Use `--exposure-column exposure_direct` or `exposure_regional` for the two
component robustness specifications.

The input has one row per GKZ-year. `gkz`, `year`, and `expenditure` are
required; every additional column is a time-varying control:

```text
gkz,year,expenditure,population,unemployment_rate,...
```

Blank expenditure or control values mean that the variable could not be found
for that GKZ-year, so the entire row is excluded through complete-case
filtering. Numeric zeroes are genuine values and remain in the level analysis.
The default outcome is expenditure in levels, fixed effects are always `gkz`
and `year`, and standard errors are clustered by GKZ. Unknown-coverage exposure
rows (`data_found=false`) are excluded by default instead of being treated as
clean zeroes. The command writes coefficient results, the exact estimation
sample, model metadata with all drop counts, and a text summary under
`data/regression/`.

See [`docs/regression.md`](docs/regression.md) for the strict input schemas,
options, output interpretation, and causal-identification requirements.

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
| `data/sources/registry.csv` | Official URLs, stable IDs, and acquisition policy |
| `data/sources/downloads/` | Cached snapshots for `download` sources |
| `data/sources/download_manifest.json` | Access time, byte size, and SHA-256 |
| `data/sources/curated/*.csv` | Reviewed propositions and participant aliases |
| `data/sources/review/*.csv` | Decisions about ambiguous court-table entries |
| `data/review/` | Generated procurement candidates awaiting review |
| `data/raw/*.csv` | Generated, normalized classifier inputs and crosswalk |
| `data/processed/*.csv` | Long panel, wide exposure matrix, and rule-level audit |

The generated normalized tables are:

| File | Role |
|---|---|
| `municipalities.csv` | Fixed 2024 GKZ universe |
| `municipality_crosswalk.csv` | Official historical-to-2024 GKZ mappings |
| `direct_evidence.csv` | Dated municipality findings |
| `cartel_periods.csv` | Participant period, legal status, eligibility, and region |
| `regional_exposure.csv` | Dated, locator-backed Bundesland project evidence for the preliminary proxy |
| `contracts.csv` | Manually accepted municipality–supplier contracts |
| `association_exposure.csv` | Dated association findings |
| `association_memberships.csv` | Dated municipal membership intervals |

The source parser uses exact municipality names and stable participant or
association IDs. It never labels every place-name hit in a legal document:
addresses, private customers, facilities, districts, and comparison locations
are not automatically municipality exposure.

Four BWB notice pages currently return a Sucuri JavaScript challenge to
automated clients. They remain registered as browser-reviewed
`citation_only` sources and point to the downloadable June 2026 BWB FAQ as a
supporting snapshot. The downloader does not attempt to bypass that challenge.
Validation verifies the FAQ bytes and the registry relationship, while making
clear that the notice pages themselves have no local checksum.

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

The regional research ledger records all 33 FCC project candidates: 29 are
accepted for their stated Bundesland-year, one facility row is pending, and
three private-customer or wastewater rows are rejected. District references
can support only the broad Bundesland proxy, never direct municipality
exposure. The participant-by-Bundesland-year matrix records unverified cells
as research gaps rather than zeroes.

## `data_found` and current coverage

`data_found` is municipality-year specific:

| exposure | data_found | Interpretation |
|---:|:---:|---|
| 1 | true | At least one annual rule is positive |
| 0 | true | Evidence covers the year but no positive rule is met |
| 0 | false | No coded evidence covers the municipality-year; zero is a default |
| 1 | false | Impossible by construction |

Direct, contract, and association records set municipality-year coverage in
their supported intervals. In addition, 2022 onward is covered for every
municipality by the project-wide post-raid non-exposure rule. Default zeroes in
2001–2021 remain unknown coverage, not confirmed clean controls. Public court
project lists are illustrative rather than exhaustive.

The last narrow official-source build, retained as a comparison baseline,
contained:

- 50,232 balanced panel rows;
- 650 historical crosswalk rows;
- 77 normalized evidence rows;
- 130 exposed municipality-years; and
- 6,409 municipality-years with `data_found=true`, including 6,279
  post-raid non-exposed rows.

The expansion is driven mainly by dated legal membership records for all 19
GABL and 15 AWS Schwechat members at the corresponding FCC project years.
The reviewed contract ledger now includes two pre-2022 municipal awards. A
Leibnitz household-waste collection award to Saubermacher overlaps the final
eligible participant period in January--March 2021. A Seewalchen am Attersee
household-biowaste award to Vorwagner, a supplier outside the eligible roster,
provides an affirmative verified zero for 2019--2021. Each award notice and the
linked notice carrying its exact performance interval is separately registered
and checksum-verified; an absent court-project entry is never used as evidence
of non-exposure.

Those counts predate the regional specification and must not be quoted as its
output. The CLI calculates and reports the regional additions from the actual
official municipality snapshot on every build.

## Current generated coverage and variation

The 2026-08-16 source build contains 50,232 balanced rows and 89 normalized
evidence rows. Before the first full post-raid year (2001--2021), the combined
preliminary regional specification has **8,512 exposed municipality-years**
and **3 verified-unexposed municipality-years**. The direct-only specification
has 131 exposed and the same 3 verified-unexposed rows; the regional-only
specification has 8,511 exposed rows and no region-verified zeroes.

All three measures retain variation after absorbing both GKZ and calendar-year
fixed effects: the two-way-demeaned sums of squares are 3,756.756 (combined),
112.976 (direct-only), and 3,756.043 (regional-only). This mechanical result
does not make the selective evidence coverage causal or supply a clean control
group.

The current review inventory contains 29 accepted, one pending, and three
rejected regional candidates, all from the already registered FCC decision.
No additional source was accepted during the 2026-08-14 re-review because the
execution network blocked the Austrian official-source hosts. The protected
BWB participant pages and unverified participant-state-years remain outside
regional treatment rather than being inferred from snippets or prior scope
summaries.

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
contract-review gating, citation-only download exclusion, wide-output shape,
the post-raid non-exposure invariant, fixed-effects coefficient recovery,
unknown-coverage exclusion, regression schema/rank checks, and paginated TED
candidate generation.

See [`docs/data_sources.md`](docs/data_sources.md) for the ingestion runbook,
[`docs/methodology.md`](docs/methodology.md) for exposure classification, and
[`docs/regression.md`](docs/regression.md) for estimation.
