# Inputs and source collection

The repository separates downloading, validation, research coding,
normalization, and classification. Only the municipality universe is a
complete machine-readable dataset. Court decisions, procurement records, and
historical association membership require source-specific review.

## Reproducible workflow

Run the whole pipeline with:

```bash
uv sync --locked
uv run awm-build
```

The command:

1. downloads missing sources listed in `data/sources/registry.csv`;
2. reuses unchanged cached snapshots by default;
3. verifies source type, byte size, and SHA-256 checksum;
4. resolves reviewed municipality evidence to the 2024 GKZ universe;
5. writes six normalized classifier inputs and a source log to `data/raw`;
6. writes the 2001–2024 municipality-year panel and audit to
   `data/processed`.

For staged operation:

```bash
uv run awm-sources download
uv run awm-sources validate
uv run awm-sources build
uv run awm-exposure
```

Use `uv run awm-build --offline` when the verified snapshots already exist and
network access is undesirable. Use `--refresh` only when intentionally
replacing cached server copies.

## Ingestion safeguards

Every downloaded source receives a stable `source_id`. The generated
`data/sources/download_manifest.json` records:

- official URL and local filename;
- UTC access time;
- byte size; and
- SHA-256 checksum.

Ordinary runs do not overwrite snapshots. Before reuse, the downloader checks
the current byte size and checksum against the manifest and fails if the cache
changed. Refreshes use HTTP retries and replace a file atomically only after a
non-empty response with the expected ZIP, PDF, or HTML signature is received.

The `validate` stage checks that:

- every registry row has an HTTPS URL and path confined to `data/sources`;
- every registered download exists;
- registry URLs and filenames match the manifest;
- cached byte sizes and checksums still match; and
- every curated `source_id` is present in the registry.

Generated CSVs are also written atomically. A failed download, validation, or
normalization therefore does not leave a partially written analysis table.

## Directory roles

| Path | Role | Committed |
|---|---|:---:|
| `data/sources/registry.csv` | Official URL registry and stable source IDs | yes |
| `data/sources/curated/*.csv` | Reviewed propositions extracted from sources | yes |
| `data/sources/downloads/` | Exact downloaded snapshots | no |
| `data/sources/download_manifest.json` | Snapshot provenance and checksums | no |
| `data/raw/*.csv` | Generated, GKZ-normalized inputs and source log | no |
| `data/processed/*.csv` | Generated panel and detailed audit | no |

Do not hand-edit `data/raw` or `data/processed`. Amend the registry or curated
records and rebuild.

## 1. Harmonized municipality universe

Generated file: `municipalities.csv`

| Column | Description |
|---|---|
| `gkz` | Five-digit Statistics Austria municipality identifier |
| `municipality_name` | Official municipality name |

The default source is Statistics Austria's municipality WFS snapshot at
2024-01-01:

<https://data.statistik.gv.at/web/meta.jsp?dataset=OGDEXT_GEM_1>

The parser reads only the official identifier and name attributes (`ID` and
`NAME`, with support for `G_ID` and `G_NAME`) and ignores geometry. The WFS
represents Vienna with 23 district geometries; the code collapses them to
municipality `Wien`, GKZ `90001`. The resulting universe has 2,093 GKZ values.

The exposure output crosses this one universe with all years 2001–2024. It is a
fixed-geography panel, not a reconstruction of contemporaneous municipal
boundaries. Statistics Austria's WFS metadata is historized from 2011 onward,
so a full annual-boundary design beginning in 2001 would additionally require a
pre-2011 universe and explicit merger/split crosswalks.

To select another registered reference vintage:

```bash
uv run awm-build \
  --municipality-source-id statistik_austria_municipalities_YEAR
```

Do not mix a different universe into an analysis without documenting the
territorial estimand and crosswalking historical evidence.

## 2. Direct municipality evidence

Generated file: `direct_evidence.csv`

| Column | Description |
|---|---|
| `gkz` | Municipality resolved against the selected universe |
| `exposed` | Reviewed `1`/`0` finding |
| `exposure_start`, `exposure_end` | Inclusive supported interval |
| `source_id`, `source_url` | Stable citation and official URL |
| `notes` | Decision location and narrow coding proposition |

The current records are reviewed municipality/customer entries in Cartel Court
decision 27 Kt 1/24k, downloaded from the Austrian Justice Ministry's Cartel Act
§37 publication database:

<https://edikte.justiz.gv.at/edikte/ek/ekedi17.nsf/suche!OpenForm>

The curated table records the specific project year or years stated in the
decision. Non-contiguous years use separate rows. This is what prevents a
single documented incident from becoming an ever-exposed municipality.

Curated inputs use exact official municipality names. The builder converts the
name to GKZ and never uses fuzzy matching. If an official name is ambiguous,
the row must supply the intended current `gkz`. If a historical municipality no
longer exists in the 2024 universe, its mapping must be researched and
documented before the row is added.

Broad place-name extraction remains deliberately excluded. A decision may
mention a company address, project location, or comparison municipality without
identifying an affected contracting customer.

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

The BWB's June 2026 FAQ is retained as a discovery/status source, but its
industry-wide dates are not automatically assigned to every named firm. Add a
participant only when an authoritative source supports that participant's own
period. Represent a discontinuous period with multiple rows under the same
`participant_id`.

## 4. Municipality contracts

Generated file: `contracts.csv`

| Column | Description |
|---|---|
| `gkz` | Contracting municipality |
| `participant_id` | Verified supplier ID |
| `contract_start`, `contract_end` | Supported performance interval |
| `source_id`, `source_url`, `notes` | Award/contract citation |

The current file is header-only. This is an evidence decision, not an ingestion
failure. The initial court decisions document collusive projects but often do
not establish which participant held a municipality contract throughout a
defensible performance interval.

Potential collection sources include:

- Austria's procurement search: <https://ausschreibungen.usp.gv.at/>
- TED Search API: <https://docs.ted.europa.eu/api/latest/search.html>
- municipal and association award notices;
- council minutes, contracts, budgets, and annual reports.

Enter a row only when the source identifies the municipality, supplier, and a
defensible interval. A call for tenders alone is not an award. Map firm aliases
deliberately to a stable `participant_id`; the classifier never fuzzy-matches
company names.

## 5. Association exposure

Generated file: `association_exposure.csv`

| Column | Description |
|---|---|
| `association_id`, `association_name` | Stable association identity |
| `exposed` | Reviewed status |
| `exposure_start`, `exposure_end` | Inclusive supported interval |
| `source_id`, `source_url`, `notes` | Citation and coding basis |

Current rows code waste associations named as affected projects in
27 Kt 1/24k, using the years shown in the decision. Repeated non-contiguous
conduct is stored as separate rows.

An association finding is not copied directly to every current member.
Propagation occurs only after a dated membership row and exposure row overlap
within a panel year.

## 6. Association membership

Generated file: `association_memberships.csv`

| Column | Description |
|---|---|
| `gkz` | Member municipality |
| `association_id` | Stable association identity |
| `membership_start`, `membership_end` | Source-supported interval |
| `source_id`, `source_url`, `notes` | Membership citation |

The initial records use the official GVA Mödling history where it gives specific
entry dates:

<https://gvamoedling.at/ueber-uns/verband-und-gemeinden/>

The registry also snapshots GABL's current member page for future research.
Those municipalities are not coded historically because the current page does
not establish membership during the association's 2015 or 2018 exposure
events. Current membership must not be projected backward.

## Adding source-backed evidence

1. Add an HTTPS URL, confined local filename, description, and unique
   `source_id` to `data/sources/registry.csv`.
2. Run `uv run awm-sources download`.
3. Read the downloaded snapshot and add only the proposition it supports to the
   relevant `data/sources/curated/*.csv`.
4. Record the narrow date interval, source location, and uncertainty in
   `notes`.
5. Run `uv run awm-sources validate`.
6. Run `uv run awm-build --offline`.
7. Inspect the raw row, source log, final audit rows, and coverage counts.
8. Run the complete test suite.

URLs alone are not durable research provenance. Preserve the source ID,
checksum, access time, legal decision/publication date, exact proposition, and
temporal interpretation together when exporting the analysis for litigation or
publication.
