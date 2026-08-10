# Methodology

## Unit and target

The default output is the balanced domain:

\[
\mathcal{I}_{2024}\times\{2001,\ldots,2024\},
\]

where \(\mathcal{I}_{2024}\) is Statistics Austria's municipality universe on
2024-01-01.

The same exposure values are also emitted as a wide convenience matrix with
one row per GKZ and one column for each panel year. The long file remains the
canonical analytical output because it retains `data_found`.

For 2024-geography municipality \(i\) and calendar year \(t\):

\[
E_{it}=\max(D_{it},C_{it},A_{it}),
\]

where:

- \(D_{it}\) is dated direct municipality evidence;
- \(C_{it}\) is an accepted municipality contract intersecting an eligible
  final participant period in a supported region; and
- \(A_{it}\) is dated association exposure intersecting dated membership.

This is an evidence classification, not an estimate of damages or cartel
intensity.

## Evidence provenance

The source registry distinguishes checksum-verified downloads from
browser-reviewed citations. Four BWB participant notice pages are currently
`citation_only` because their Sucuri JavaScript challenge prevents ordinary
HTTP acquisition. The official June 2026 BWB FAQ remains a verified supporting
snapshot, while the individual page URLs preserve the finer citations used for
participant-specific dates and scope.

This distinction affects reproducibility, not the exposure rule: a checksum
shows which bytes were reviewed but cannot validate the legal interpretation.
The source log therefore leaves hashes blank for citation-only pages and names
their supporting snapshot explicitly. Page-specific claims should be manually
archived before publication or litigation if the official site still blocks
automated snapshots.

The project also defines \(P_t=1\) for full calendar years beginning in 2022.
The registered BWB material and participant findings place the end of the
cartel in March 2021. Because \(E_{it}\) is positive for any supported day in a
year, 2021 remains a potentially exposed mixed year; 2022 is the first annual
unit wholly after the raids. The classifier enforces:

\[
P_t=1 \Longrightarrow E_{it}=0\quad\text{for every }i.
\]

A positive direct, contract, or association rule in a post-raid year stops the
build as contradictory evidence rather than being silently overwritten.

## Date and overlap rule

All intervals are inclusive. Inputs may use:

- `YYYY-MM-DD`;
- `YYYY-MM`, expanded to the first/last day of that month; or
- `YYYY`, expanded to January 1/December 31.

One blank boundary means open-ended. Both boundaries cannot be blank.

A rule is positive only when every required interval shares at least one
actual day with the calendar year:

\[
\max(s_1,\ldots,s_k,\text{Jan 1}_t)
\le
\min(e_1,\ldots,e_k,\text{Dec 31}_t).
\]

Thus a cartel period ending March 31 and contract starting April 1 do not
overlap even though both occur in the same year. Any positive within-year
overlap produces `1`; the annual indicator is not prorated.

## Direct rule

\(D_{it}=1\) when an affirmative direct-evidence interval for municipality
\(i\) overlaps year \(t\). A table entry for 2016 supports 2016 only.
Non-contiguous years are separate rows.

The FCC extraction inventory distinguishes:

- accepted municipality or association projects;
- unresolved district, facility, or service-scope entries; and
- excluded private-customer or out-of-scope wastewater entries.

The court's project list is treated as documented examples, not an exhaustive
victim register. Absence from the table is unknown, not direct evidence of
zero exposure.

An explicit direct negative row can set `data_found=true`, but cannot override
a positive contract or association rule in the same municipality-year.

## Contract rule

\(C_{it}=1\) only if all of the following are true:

1. a contract row passed manual review and has `review_status=accepted`;
2. the contract identifies municipality \(i\), a stable `participant_id`, and
   a supported performance interval;
3. a participant-period row for the same ID is `final`;
4. that period has `eligible_for_exposure=true`;
5. the municipality's Austrian state prefix is in the period's supported
   `gkz_prefixes`, unless the scope is blank/nationwide; and
6. contract, participant period, and year \(t\) share a day.

Publication date, award date, and performance period are not interchangeable.
The treatment interval follows supported service performance dates.

The default final roster is:

- FCC Austria Abfall Service AG;
- the two Huber entities;
- Saubermacher, Trügler, and pink robin as one decision group;
- the Killer entities; and
- KAB Kärntner Abfallbewirtschaftung GmbH.

Energie AG OÖ Umwelt Service is recorded as `pending_admitted` but ineligible.
Its TED notices may appear in the candidate queue; they cannot create exposure.

A verified contract sets `data_found=true` during its performance interval even
if no eligible participant period overlaps. A participant finding by itself
does not create municipality-level coverage.

## TED candidate rule

TED ingestion is intentionally upstream of treatment. The API query finds
Austrian waste-service notices and performs deterministic alias matching on
reported winner names. Every output row begins as `pending`.

The following are not sufficient for acceptance:

- a participant name anywhere in a notice;
- an association or federal buyer without a specific municipal customer;
- a tender notice without an award;
- an award without supported performance dates; or
- a place of performance that merely contains a municipality name.

Only a manually accepted, source-registered curated contract can enter the
normalized contract table. This separation prevents an API refresh or a false
name match from changing exposure.

## Association rule

\(A_{it}=1\) only when:

1. municipality \(i\)'s membership interval;
2. an affirmative exposure interval for the same `association_id`; and
3. calendar year \(t\)

share at least one day.

Current membership is never projected backward. GABL and AWS membership is
propagated because RIS law establishes founding dates and later accessions
before the relevant FCC projects. GVA Mödling is propagated only for
municipalities whose entry date is stated in its official history.

An association exposure does not automatically apply to an entire district,
to municipalities merely served by a facility, or to current members with no
historical support.

## `data_found`

Coverage is calculated separately for each GKZ-year:

- direct evidence sets coverage for its supported interval;
- an accepted contract sets coverage for its performance interval, regardless
  of whether the participant gate is positive; and
- association evidence sets coverage only where a dated membership and an
  evaluated association interval overlap; and
- the project-wide post-raid rule sets coverage for every municipality in each
  full calendar year from 2022 onward.

| exposure | data_found | Interpretation |
|---:|:---:|---|
| 1 | true | At least one rule is positive |
| 0 | true | Evidence covers the year but no positive rule is met |
| 0 | false | No coded evidence covers the row; zero is a default |
| 1 | false | Prohibited by construction |

The audit preserves rule flags, source IDs, evaluated row counts,
`data_found_reasons`, and an explicit `post_raid_non_exposure` flag. Positive
evidence wins across the three municipality channels, but a positive after
2021 is invalid because it contradicts the project-wide non-exposure period.

The present build has 130 exposed rows and 6,409 rows with data. Of those,
6,279 are post-raid zeroes: 2,093 municipalities in each of 2022–2024. These
rows establish the treatment state after the cartel, but they do not create a
cross-sectional comparison group during the cartel period. Restricting a
regression to `data_found=true` would therefore select almost entirely on
calendar time and should not be presented as a clean treated-versus-control
design. Broader pre-raid procurement coverage is still required.

## Territorial harmonization

The output uses fixed 2024 geography. Statistics Austria's administrative-
change archive maps changed codes since 2002 into that universe.

For a deterministic predecessor-to-successor chain, evidence is assigned to
the 2024 successor. When multiple predecessors merge, the 2024 unit is
positive if any mapped predecessor is positive; this is a maximum aggregation
rule and does not imply that the whole current territory was exposed.

A one-to-many historical split is not assigned automatically. The crosswalk
retains all successors as `split_requires_review`, and normalization fails
until the researcher identifies the relevant 2024 target. This avoids copying
one historical project to every successor.

The crosswalk is a harmonization device, not an annual-boundary reconstruction.
It does not make every 2024 unit historically existent, and it does not supply
pre-2002 changes. Analyses on contemporaneous municipality boundaries require
annual universes and a different panel design.

## Identification cautions

The classification alone is not a causal treatment design:

- published case material is selective and non-exhaustive;
- procurement availability and manual review are non-random;
- a cartel-period supplier relationship may itself reflect customer
  allocation;
- association propagation can make many municipalities share the same event;
- default zeroes are mostly unresearched, not confirmed unexposed;
- post-raid zeroes identify a common temporal regime, not comparable pre-raid
  untreated municipalities;
- fixed-geography merger aggregation can dilute a predecessor-level event; and
- annual binary overlap ignores value, volume, service share, and duration.

Recommended research progression:

1. expand accepted pre-2021 municipality contracts and document performance
   intervals;
2. create an explicit coverage denominator, including reviewed tenders or
   municipalities where a different supplier is confirmed;
3. report direct, contract, and association channels separately;
4. use genuinely predetermined supplier relationships where possible;
5. analyze the first genuine post-cartel competitive retender at the
   contract/tender level;
6. cluster or otherwise account for association-level common shocks; and
7. keep exposure construction independent of post-2021 outcomes.

The main panel can be used immediately for descriptive mapping and source
auditing. A causal municipal regression should wait for broader procurement
coverage or use a design that does not treat `data_found=false` as a verified
clean control.

The repository's `awm-regress` command enforces the latter safeguard by
excluding `data_found=false` rows unless an analyst explicitly opts into an
alternative specification. This protects the coding meaning of the zeroes but
does not solve the selective-coverage problem described above. See
[`regression.md`](regression.md) for the estimator, input schemas, diagnostics,
and additional identification requirements.

## Current release

The current default build contains:

- 2,093 fixed-2024 GKZ units;
- 24 years and 50,232 unique panel keys;
- 650 historical crosswalk rows;
- 77 normalized evidence rows;
- 130 exposed municipality-years;
- 6,409 rows with `data_found=true`, of which 6,279 are post-raid zeroes; and
- zero accepted municipality-contract rows.

These counts measure documented coding coverage, not the cartel's true reach.
