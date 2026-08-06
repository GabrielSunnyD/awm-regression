# Data ingestion and source collection

The pipeline separates four different claims:

```text
official snapshot or reviewed citation → reviewed proposition → normalized row → annual exposure
```

Downloaded snapshots and normalization are mechanically reproducible;
browser review of a citation-only page is not. A checksum proves that a cached
file has not changed; it does not prove that a researcher's legal interpretation
is correct.

## Reproducible build

```bash
uv sync --locked
uv run awm-build
```

The complete command:

1. downloads missing registry rows whose `acquisition_method` is `download`;
2. reuses byte-verified snapshots unless `--refresh` is requested and skips
   rows explicitly marked `citation_only`;
3. validates the registry, manifest, curated schemas, citations, review
   statuses, participant legal status, and geographic codes;
4. derives the 2024 municipality universe and historical-GKZ crosswalk;
5. resolves reviewed municipality evidence into normalized `data/raw` tables;
6. excludes all non-accepted procurement rows; and
7. builds the 2001–2024 long panel, wide exposure matrix, and audit.

For diagnosis, run the stages separately:

```bash
uv run awm-sources download
uv run awm-sources validate
uv run awm-sources build
uv run awm-exposure
```

Use:

```bash
uv run awm-build --offline
```

to forbid network requests. Use `--refresh` only when deliberately replacing
the evidence snapshots reviewed previously. Neither mode requests a
`citation_only` URL.

## Downloaded snapshots and citation-only pages

Every registry row declares one acquisition method:

| `acquisition_method` | `filename` | `supporting_snapshot_id` | Behavior |
|---|---|---|---|
| `download` | required | blank | Downloaded, format-checked, hashed, and recorded in the manifest |
| `citation_only` | blank | required | Never requested automatically; retained as a precise browser-reviewed citation |

A citation-only row must point to a registered `download` row through
`supporting_snapshot_id`. This records a reproducible supporting source without
pretending the uncached page itself was checksum-verified.

The four BWB participant notices are currently `citation_only` because BWB's
Sucuri layer returns a JavaScript-cookie challenge to non-browser clients. They
all point to `bwb_faq_2026`, a normally downloadable official PDF that
corroborates the case-wide period, named respondents, and procedural status.
The individual notice URLs remain the basis for finer participant-specific
details. Those details are browser-reviewed but not byte-reproducible until BWB
provides an automatable document endpoint.

## What validation checks

The download manifest records each source's URL, local filename, access time,
byte size, and SHA-256 hash. Validation checks that:

- registry URLs use HTTPS;
- `acquisition_method` is `download` or `citation_only`;
- download filenames cannot escape `data/sources`;
- citation-only rows have no filename and reference a registered downloadable
  supporting snapshot;
- every downloadable snapshot and manifest entry exists;
- manifest URL and filename agree with the registry;
- file signatures are plausible for ZIP, PDF, or HTML;
- cached byte sizes and SHA-256 hashes still match;
- every curated or review row cites a registered `source_id`;
- required CSV columns exist;
- participant statuses and state-prefix scopes are valid;
- a pending participant is not exposure-eligible;
- contract and alias participant IDs exist in the curated participant roster;
- procurement review statuses are valid; and
- accepted contracts contain a municipality, participant, performance
  interval, reviewer, and ISO review date.

Downloads and generated CSVs use atomic replacement so a failed operation does
not leave a partial file.

Validation does **not** establish that:

- a court decision was interpreted correctly;
- an interval was transcribed correctly;
- a buyer is truly a municipality;
- a TED result is an award rather than another notice type; or
- a contract concerns the relevant household-waste service.

Those remain review tasks. The audit table and source snapshots make that
review possible.

## Directory roles

| Path | Role | Committed |
|---|---|:---:|
| `data/sources/registry.csv` | Official URL and acquisition-policy registry | yes |
| `data/sources/curated/*.csv` | Accepted evidence, pending contract decisions, aliases | yes |
| `data/sources/review/*.csv` | Disposition inventory for ambiguous source entries | yes |
| `data/sources/downloads/` | Downloaded source bytes | no |
| `data/sources/download_manifest.json` | Snapshot hashes and provenance | no |
| `data/review/` | Generated TED candidates | no, except README |
| `data/raw/*.csv` | Generated normalized data and crosswalk | no |
| `data/processed/*.csv` | Generated long panel, wide matrix, and audit | no |

Never hand-edit `data/raw` or `data/processed`.

## Municipality universe and historical GKZ

`municipalities.csv` comes from Statistics Austria's 2024-01-01 municipality
WFS. The parser reads only official `ID`/`NAME` attributes and collapses
Vienna's 23 district geometries to municipality GKZ `90001`.

`municipality_crosswalk.csv` comes from Statistics Austria's
`aenderungenGemeinden_ab2002.ods`, embedded in the official administrative-
change archive. The parser:

1. reads changes effective no later than the selected municipality-universe
   date (`2024-01-01` by default);
2. follows multi-step GKZ chains;
3. uses official name-change records to resolve retained municipalities whose
   code changed during a later merger;
4. maps only into the selected 2024 universe; and
5. labels one-to-many results `split_requires_review`.

A curated row may supply an obsolete GKZ or exact historical name. A
one-to-one chain is normalized automatically. A split raises an error because
copying evidence to every successor could create false exposure; supply the
intended current GKZ after reviewing the source.

The crosswalk begins in 2002 because that is the machine-readable archive's
coverage. Evidence from 2001 that uses a defunct code still requires manual
research.

When selecting a different registered municipality vintage, set its validity
date as well:

```bash
uv run awm-build \
  --municipality-source-id statistik_austria_municipalities_YEAR \
  --municipality-reference-date YEAR-01-01
```

## Direct municipality evidence

`data/sources/curated/direct_evidence.csv` stores narrow, dated propositions
from the FCC decision. Exact project years are used; non-contiguous years are
separate rows.

`data/sources/review/fcc_public_project_review.csv` is the extraction
inventory. Every municipality- or association-like FCC table entry considered
for coding has an explicit disposition:

- `accepted`: represented in direct or association evidence;
- `pending`: needs municipality, ownership, or service-scope research; or
- `excluded`: private customer, wastewater, or otherwise outside scope.

This prevents the same ambiguous row from being silently reconsidered or
treated differently in a later update.

## Participant periods and aliases

`cartel_periods.csv` includes:

| Field | Meaning |
|---|---|
| `participant_id` | Stable group ID used by contracts and aliases |
| `cartel_start`, `cartel_end` | Participant-specific supported interval |
| `legal_status` | `final` or `pending_admitted` |
| `eligible_for_exposure` | Whether the default contract rule may use it |
| `gkz_prefixes` | Supported state prefixes, separated with `|`; blank is nationwide |
| `source_id`, `notes` | Decision/status source and coding basis |

The finalized default roster comprises FCC; the Huber entities;
Saubermacher/Trügler/pink robin; Killer; and KAB. Energie AG OÖ Umwelt Service
is retained as a discoverable pending/admitted case but is ineligible.

`participant_aliases.csv` contains source-backed legal and historical names for
TED matching. Aliases generate candidates only; they never join directly to
the exposure panel.

## Procurement candidates and accepted contracts

Generate candidates with:

```bash
uv run awm-ted
```

The command calls TED's unauthenticated `POST /v3/notices/search` endpoint with:

- Austrian buyers;
- hierarchical waste CPV `90500000`;
- publication dates 2001-01-01 through 2024-12-31 by default; and
- paginated, latest-version results.

It retains notices whose reported winner contains a reviewed participant alias
and writes all matches as `pending`. TED coverage and normalized fields are
not uniform over the full period, so this is a search aid rather than a
complete procurement census.

Review each candidate against the underlying notice. Confirm:

1. a specific municipality is the contracting buyer;
2. the notice establishes an award to the matched participant;
3. the service is relevant municipal waste work;
4. performance start and end dates are supported;
5. the municipality maps to the intended 2024 GKZ; and
6. the notice is registered and snapshotted under a stable `source_id`.

Then add a row to `data/sources/curated/contracts.csv`. Example:

```csv
candidate_id,review_status,municipality_name,gkz,participant_id,contract_start,contract_end,source_id,source_url,reviewer,reviewed_at,notes
ted:123456-2016:fcc_austria,accepted,Fischamend,,fcc_austria,2017-07-01,2020-06-30,ted_123456_2016,,Researcher Name,2026-07-30,"Award and performance period verified in sections X and Y."
```

Pending and rejected rows may remain in the curated table as a research log,
but only `accepted` rows are emitted to `data/raw/contracts.csv`. A tender
announcement without a winner and performance interval is not enough.

## Association exposure and membership

`association_exposure.csv` stores dated association projects from the FCC
decision. It now includes the previously omitted GABL 2013–2014 and AWS
Schwechat 2016–2017 entries.

`association_memberships.csv` stores only dated legal or official membership:

- RIS §52 supports GABL's founding members, Hof's 1993 accession, and the
  separate 1997 accessions of Berg and Wolfsthal;
- RIS §75 supports AWS's 13 founding members, Gerasdorf's 1997 accession, and
  Fischamend's 2005 accession; and
- the official GVA Mödling history supports only the entry dates it reports.

Current association web pages are not projected backward. Propagation occurs
only when membership, association exposure, and the panel year share at least
one actual day.

## Post-raid annual coverage

The registered BWB FAQ and participant findings place the end of the documented
cartel in March 2021. The panel therefore treats 2022 as the first complete
post-raid calendar year. For every municipality, 2022–2024 receive:

```text
exposure=0,data_found=true
```

The audit marks these rows with `post_raid_non_exposure=1` and includes
`post_raid` in `data_found_reasons`. The rule does not apply to 2021 because an
annual exposure indicator remains positive if supported exposure occurred on
any day from January through March. Any curated rule that attempts to create a
positive exposure after 2021 stops the build for review.

The wide file `data/processed/municipality_year_exposure_wide.csv` contains
only annual exposure values. Use the long file when `data_found` is needed;
otherwise unsupported pre-raid zeroes and supported post-raid zeroes are
indistinguishable.

## Adding a new source

1. Add an HTTPS URL, description, unique `source_id`, and acquisition method to
   `data/sources/registry.csv`. Prefer `download`. Supply a confined filename
   and leave `supporting_snapshot_id` blank.
2. Run `uv run awm-sources download`.
3. Read the downloaded snapshot.
4. Add only the narrow supported proposition to the appropriate curated CSV.
5. Record exact dates, source location, uncertainty, and any review decision.
6. Run:

   ```bash
   uv run awm-sources validate
   uv run awm-build --offline
   uv run python -m unittest discover -s tests -v
   ```

7. Inspect `data/raw/source_log.csv`,
   `data/raw/municipality_crosswalk.csv`, and the affected rows in
   `data/processed/municipality_year_exposure_audit.csv`.

Use `citation_only` only when an official page cannot be acquired by a normal
HTTP client and has been reviewed in a browser. Leave `filename` blank, provide
a downloadable `supporting_snapshot_id`, and document which details depend on
the uncached page. Do not use this mode merely to avoid registering or
preserving an available snapshot.

For publication or litigation, preserve the registry, manifest, available
snapshots, curated records, generated source log, code commit, and methodology
version together. Archive citation-only pages manually where permitted before
relying on their page-specific details in a final evidentiary record.
