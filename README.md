# Austrian waste-cartel municipality-year exposure

This project builds a simple, auditable exposure panel for Austrian
municipalities:

```text
gkz,year,exposure,data_found
```

The default output is a balanced panel of every municipality in Statistics
Austria's 2024 GKZ universe for every year from 2001 through 2024. The current
official universe has 2,093 municipalities, so the output contains 50,232 rows.
GKZ (*Gemeindekennziffer*) is the official abbreviation.

`exposure=1` for municipality \(i\) in year \(t\) when at least one reviewed
source supports one of these rules during that year:

1. direct municipality evidence overlaps year \(t\);
2. a verified municipality contract, the same participant's court-supported
   cartel period, and year \(t\) share at least one day; or
3. a municipality's association-membership interval, a reviewed affirmative
   association-exposure interval, and year \(t\) share at least one day.

Exposure is not carried forward from another year. A municipality documented
in one project year is positive in that year only unless another dated record
supports additional years.

## Reproduce the panel

Install [`uv`](https://docs.astral.sh/uv/), clone the repository, and run:

```bash
uv sync --locked
uv run awm-build
```

`awm-build` performs the entire workflow:

1. download or reuse official source snapshots;
2. verify cached bytes against the SHA-256 manifest;
3. normalize reviewed evidence into `data/raw`;
4. build the 2001–2024 panel and audit table in `data/processed`.

Use the existing verified snapshots without network requests:

```bash
uv run awm-build --offline
```

Replace snapshots only when an intentional source refresh is needed:

```bash
uv run awm-build --refresh
```

The generated outputs are:

- `data/processed/municipality_year_exposure.csv` — simple analysis panel;
- `data/processed/municipality_year_exposure_audit.csv` — municipality name,
  rule flags, row counts, and positive source IDs for every GKZ-year.

Pass `--omit-data-found` for a three-column main output or `--no-audit` to skip
the detailed table. The year range is configurable:

```bash
uv run awm-exposure --start-year 2001 --end-year 2024
```

The source stages can also be run independently:

```bash
uv run awm-sources download
uv run awm-sources validate
uv run awm-sources build
uv run awm-exposure
```

## Evidence architecture

The project keeps evidence acquisition, reviewed coding, normalized inputs, and
classification separate:

| Layer | Role |
|---|---|
| `data/sources/registry.csv` | Official URLs and stable citation IDs |
| `data/sources/downloads/` | Cached source snapshots |
| `data/sources/download_manifest.json` | Access times, byte sizes, and SHA-256 checksums |
| `data/sources/curated/*.csv` | Narrow propositions reviewed by a researcher |
| `data/raw/*.csv` | Generated, GKZ-normalized inputs |
| `data/processed/*.csv` | Final panel and rule-level audit |

The six classifier inputs are:

| File | Role |
|---|---|
| `municipalities.csv` | Harmonized 2024 GKZ universe |
| `direct_evidence.csv` | Dated municipality-level positive or negative findings |
| `cartel_periods.csv` | Participant-specific infringement intervals |
| `contracts.csv` | Verified municipality–supplier contract intervals |
| `association_exposure.csv` | Dated association-level findings |
| `association_memberships.csv` | Dated municipal membership intervals |

Statistics Austria's 2024 WFS SHAPE-ZIP supplies the municipality universe. The
parser reads the official identifiers and names, ignores geometry, and
collapses Vienna's 23 district geometries to municipality GKZ `90001`.

Court documents are not classified with unrestricted place-name matching. A
legal decision may contain company addresses, comparison locations, or
anonymized entities that are not evidence that a municipality was affected.
Reviewed rows therefore retain an exact source ID, supported date interval, and
coding note. Municipality names are resolved by exact match; firm and
association joins use stable researcher-created IDs.

## `data_found` and unknown coverage

`data_found` is calculated separately for each municipality-year:

| exposure | data_found | Interpretation |
|---:|:---:|---|
| 1 | true | At least one dated rule supports exposure in that year |
| 0 | true | Relevant evidence covers that year but no positive rule is met |
| 0 | false | No coded evidence covers that municipality-year; zero is a default |
| 1 | false | Impossible by construction |

Most current zeroes are the third category and must not be interpreted as proof
of no exposure. Public court project lists are not exhaustive, historical
procurement data remain fragmented, and `contracts.csv` is intentionally empty
until municipality–supplier awards and performance intervals can be verified.

With the currently curated evidence, the default build has 23 exposed
municipality-years and 23 municipality-years with `data_found=true`. These
figures describe current coding coverage, not the true size of the cartel.

## Territorial interpretation

The balanced panel uses one harmonized territorial vintage: the set of GKZ
values valid on 2024-01-01. It does not claim that every 2024 municipality
existed under the same code in every earlier year. Historical evidence for a
predecessor municipality must be deliberately crosswalked to the chosen 2024
unit before it is curated; unknown or obsolete GKZ values cause a hard error.

This fixed geography is useful for merging with a regression panel already
harmonized to 2024 boundaries. A contemporaneous-boundary panel would be a
different estimand and would require annual historical universes and explicit
merger crosswalks.

## Testing

Run:

```bash
uv run python -m unittest discover -s tests -v
```

Tests cover annual rule timing, partial-year intersections, balanced-panel
completeness, unknown years, malformed values, stale GKZ rejection, exact
municipality matching, Vienna normalization, source-cache checksums, download
refresh behavior, and the source-to-panel path.

See [`docs/data_sources.md`](docs/data_sources.md) for collection and ingestion
details and [`docs/methodology.md`](docs/methodology.md) for the classification
rules and identification cautions.
