# Inputs and source collection

The repository separates downloading, research coding, normalization, and
classification. This is intentional: only the municipality universe is a
complete machine-readable dataset. Court decisions, procurement records, and
historical association membership require source-specific review.

## Reproducible workflow

```bash
uv sync --locked
uv run awm-sources all
uv run awm-exposure
```

`awm-sources all` performs two operations:

1. It downloads every URL in `data/sources/registry.csv` to
   `data/sources/downloads/`.
2. It combines the official municipality universe with reviewed records in
   `data/sources/curated/` and writes the required CSVs to `data/raw/`.

Each download is recorded in `data/sources/download_manifest.json` with its
URL, access time, byte count, and SHA-256 checksum. The generated
`data/raw/source_log.csv` carries that provenance into the analysis layer.
Cached snapshots are reused by default. Pass `--refresh` to replace them
explicitly.

## Directory roles

| Path | Role | Committed |
|---|---|:---:|
| `data/sources/registry.csv` | Official URL registry and stable source IDs | yes |
| `data/sources/curated/*.csv` | Reviewed propositions extracted from sources | yes |
| `data/sources/downloads/` | Exact downloaded documents and datasets | no |
| `data/sources/download_manifest.json` | Snapshot checksums and access times | no |
| `data/raw/*.csv` | Generated, GKZ-normalized classifier inputs | no |

Do not hand-edit `data/raw`. Amend the registry or curated records and rebuild.

## 1. Municipality universe

Generated file: `municipalities.csv`

| Column | Description |
|---|---|
| `gkz` | Five-digit Statistics Austria municipality identifier |
| `municipality_name` | Official municipality name |

Source: Statistics Austria's WFS SHAPE-ZIP for municipalities at
2026-01-01:

<https://data.statistik.gv.at/web/meta.jsp?dataset=OGDEXT_GEM_1>

The parser reads only the official identifier/name attributes (`G_ID` and
`G_NAME`; older fixtures may use `ID` and `NAME`). The WFS geometry represents
Vienna using 23 municipal districts. The code collapses those district polygons
to the single municipality `Wien`, GKZ `90001`, so the CSV matches the national
municipality concept.

To use a different territorial vintage, add its official WFS URL to
`registry.csv` and run:

```bash
uv run awm-sources all \
  --municipality-source-id statistik_austria_municipalities_YEAR
```

Do not combine vintages without a documented historical crosswalk.

## 2. Direct municipality evidence

Generated file: `direct_evidence.csv`

| Column | Description |
|---|---|
| `gkz` | Municipality GKZ resolved from the selected universe |
| `exposed` | Reviewed `1`/`0` finding |
| `source_id` | Stable registry citation |
| `source_url` | Official document URL |
| `notes` | Decision section, year, and coding proposition |

The current records are reviewed municipality/customer entries in the
published FCC Cartel Court decision, 27 Kt 1/24k. The document is downloaded
from the Austrian Justice Ministry's Cartel Act §37 publication database:

<https://edikte.justiz.gv.at/edikte/ek/ekedi17.nsf/suche!OpenForm>

Curated inputs use official municipality names. The builder requires an exact
name match and converts it to GKZ. When an official name occurs under more than
one GKZ, the curated row must include `gkz`; the code never guesses.

Broad place-name extraction is deliberately excluded. A court decision can
mention a municipality as an address, project location, or comparison without
identifying it as an affected contracting customer.

## 3. Participant infringement periods

Generated file: `cartel_periods.csv`

| Column | Description |
|---|---|
| `participant_id` | Stable researcher-created firm/group ID |
| `participant_name` | Display name |
| `cartel_start`, `cartel_end` | Court-supported participation interval |
| `source_id`, `source_url`, `notes` | Citation and coding basis |

The current records cover:

- FCC Austria Abfall Service AG, July 2002–March 2021, from 27 Kt 1/24k;
- the two Huber entities, 2003–March 2021, from 28 Kt 1/25v.

The BWB's June 2026 FAQ is downloaded as a discovery/status source, but a
company is not assigned the FAQ's industry-wide period automatically. Add a
participant only when its own court decision supports a period. If the
supported period is discontinuous, add multiple rows under one
`participant_id`.

## 4. Municipality contracts

Generated file: `contracts.csv`

| Column | Description |
|---|---|
| `gkz` | Contracting municipality |
| `participant_id` | Verified supplier ID |
| `contract_start`, `contract_end` | Supported performance interval |
| `source_id`, `source_url`, `notes` | Award/contract citation |

The current file is header-only. This is a deliberate evidence decision, not a
pipeline failure. The initial reviewed court decisions prove collusive conduct
for named customers but often do not establish which participant ultimately
held a municipality contract for the full performance interval.

Future contract collection can use:

- Austria's procurement search: <https://ausschreibungen.usp.gv.at/>
- TED Search API: <https://docs.ted.europa.eu/api/latest/search.html>
- municipal or association award notices, council minutes, contracts, budgets,
  and annual reports.

Enter a record only when the source identifies the municipality, supplier, and
a defensible date interval. A call for tenders alone is not an award. Preserve
firm aliases in the research notes and map them deliberately to an existing
`participant_id`; the classifier does not fuzzy-match companies.

## 5. Association exposure

Generated file: `association_exposure.csv`

| Column | Description |
|---|---|
| `association_id`, `association_name` | Stable association identity |
| `exposed` | Reviewed status |
| `exposure_start`, `exposure_end` | Supported interval |
| `source_id`, `source_url`, `notes` | Citation and coding basis |

The current rows code waste associations named as affected projects in
27 Kt 1/24k, using the specific years shown by the decision. Repeated
non-contiguous conduct is stored as separate rows.

An association record is not duplicated as direct evidence for every member.
Municipality propagation happens only through the membership table and interval
overlap.

## 6. Association membership

Generated file: `association_memberships.csv`

| Column | Description |
|---|---|
| `gkz` | Member municipality |
| `association_id` | Stable association identity |
| `membership_start`, `membership_end` | Source-supported interval |
| `source_id`, `source_url`, `notes` | Membership citation |

The initial records use the official GVA Mödling history page where it provides
specific entry dates:

<https://gvamoedling.at/ueber-uns/verband-und-gemeinden/>

The registry also snapshots GABL's current member page for future research.
Those current members are not yet coded historically because the page does not
show that every current municipality belonged during the 2015 or 2018 exposed
intervals. Current membership must not be projected backward without evidence.

## Adding a source-backed row

1. Add an HTTPS URL, filename, description, and unique `source_id` to
   `data/sources/registry.csv`.
2. Run `uv run awm-sources download`.
3. Read the downloaded snapshot and add a narrow proposition to the relevant
   `data/sources/curated/*.csv`.
4. Include the page, table row, paragraph, and any uncertainty in `notes`.
5. Run `uv run awm-sources build` and inspect the generated row and source log.
6. Run the unit tests and `uv run awm-exposure`.

URLs alone are not durable research provenance. Keep the stable source ID,
checksum, decision/publication date, access time, and exact proposition together
when exporting the analysis for litigation or publication.

