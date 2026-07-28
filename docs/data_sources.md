# Inputs and source collection

The pipeline separates source collection from classification. Researchers enter
source-backed observations into six small CSVs; the code performs only exact ID
joins, interval overlap, validation, and aggregation.

## 1. Municipality universe

File: `municipalities.csv`

| Column | Required | Description |
|---|:---:|---|
| `gkz` | yes | Five-digit Statistics Austria municipality identifier |
| `municipality_name` | no | Name for the audit output |

Use a single Statistics Austria territorial vintage and record it in the
research log. The official regional-division page reports the current number of
municipalities and links the municipality directory and open WFS data:

- https://www.statistik.at/services/tools/regionale-internationale-daten/regionale-daten-und-gliederungen/regionale-gliederungen
- https://data.statistik.gv.at/web/meta.jsp?dataset=OGDEXT_GEM_1
- current GKZ-sorted list:
  https://www.statistik.at/verzeichnis/reglisten/gemliste_knz.pdf

Convert the selected official table to the two-column CSV schema. Do not merge
municipality vintages without an explicit historical crosswalk.

## 2. Direct municipality evidence

File: `direct_evidence.csv`

| Column | Required | Description |
|---|:---:|---|
| `gkz` | yes | Municipality GKZ |
| `exposed` | yes | `1`/`0` or `true`/`false` |
| `source_id` | recommended | Stable citation key |
| `source_url` | recommended | Direct document URL |
| `notes` | no | Page, paragraph, quote paraphrase, or coding note |

Search the Austrian Justice Ministry's Cartel Act §37 publication database by
company name, then code a municipality only when the source supports the
municipality-level conclusion:

- https://edikte.justiz.gv.at/edikte/ek/ekedi17.nsf/suche!OpenForm
- BWB case overview and participant status:
  https://www.bwb.gv.at/fileadmin/user_upload/FAQ_Abfallkartell_Juni_2026__2_Barrierefrei.pdf

Court documents may identify customers, tenders, geographic allocations, waste
associations, or named municipalities. Preserve the exact page or paragraph in
`notes`.

## 3. Participant infringement periods

File: `cartel_periods.csv`

| Column | Required | Description |
|---|:---:|---|
| `participant_id` | yes | Stable researcher-created firm/group ID |
| `participant_name` | no | Display name |
| `cartel_start` | yes, may be blank | Supported interval start |
| `cartel_end` | yes, may be blank | Supported interval end |
| `source_id` | recommended | Court/BWB citation key |
| `source_url` | recommended | Direct decision URL |
| `notes` | no | Scope, uncertainty, or group-company mapping |

Use periods found or accepted by the court for that participant, not a single
industry-wide date automatically applied to every company. If a decision
supports discontinuous periods, use multiple rows with the same
`participant_id`.

Keep corporate-name aliases in a separate research crosswalk and manually assign
one stable `participant_id`. The pipeline deliberately does not fuzzy-match
companies.

## 4. Municipality contracts

File: `contracts.csv`

| Column | Required | Description |
|---|:---:|---|
| `gkz` | yes | Contracting municipality |
| `participant_id` | yes | Stable supplier ID; it may be absent from `cartel_periods.csv` |
| `contract_start` | yes, may be blank | Contract/performance interval start |
| `contract_end` | yes, may be blank | Contract/performance interval end |
| `source_id` | recommended | Notice, award, council minute, or contract key |
| `source_url` | recommended | Direct record URL |
| `notes` | no | Lot, CPV, waste stream, or ambiguity |

Useful procurement sources include:

- Austria's public procurement search:
  https://ausschreibungen.usp.gv.at/
- TED Search API documentation:
  https://docs.ted.europa.eu/api/latest/search.html
- municipal council minutes, budgets, annual reports, tender documents, and
  contract-award notices on municipality or association websites.

Search waste-related CPV categories, buyer names, and confirmed participant
aliases. Historical and below-threshold coverage is incomplete, so retain
`data_found` and document the search window.

## 5. Association exposure

File: `association_exposure.csv`

| Column | Required | Description |
|---|:---:|---|
| `association_id` | yes | Stable waste-association ID |
| `association_name` | no | Display name |
| `exposed` | yes | Evaluated exposure status |
| `exposure_start` | yes, may be blank | Association exposure interval start |
| `exposure_end` | yes, may be blank | Association exposure interval end |
| `source_id` | recommended | Supporting citation key |
| `source_url` | recommended | Direct URL |
| `notes` | no | Contract, participant, or coding basis |

An association can be coded from a court mention or from a supported contract
with a cartel participant. Do not duplicate every member as direct evidence;
membership propagation is handled by the next file.

## 6. Association membership

File: `association_memberships.csv`

| Column | Required | Description |
|---|:---:|---|
| `gkz` | yes | Member municipality |
| `association_id` | yes | Stable association ID |
| `membership_start` | yes, may be blank | Membership interval start |
| `membership_end` | yes, may be blank | Membership interval end |
| `source_id` | recommended | Membership-list citation |
| `source_url` | recommended | Direct URL |
| `notes` | no | Historical-boundary or membership note |

Use statutes, official member directories, annual reports, and historical
association documents. Current membership should not be projected backward
unless the source supports continuity.

## Source log recommendation

`source_id` should resolve to an immutable research log containing document
title, publisher, publication/decision date, access date, archived path or
checksum, and the exact proposition coded. URLs alone are not durable enough for
litigation or reproducibility work.

