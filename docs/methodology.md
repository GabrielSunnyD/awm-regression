# Methodology

## Unit and target

The main output is a balanced municipality-year panel. Its default domain is:

\[
\mathcal{I}_{2024} \times \{2001,\ldots,2024\},
\]

where \(\mathcal{I}_{2024}\) is the set of GKZ values in Statistics Austria's
municipality universe on 2024-01-01.

For municipality \(i\) and calendar year \(t\), the binary classification is:

\[
E_{it} = \max(D_{it}, C_{it}, A_{it}),
\]

where:

- \(D_{it}=1\) when affirmative direct municipal evidence overlaps year \(t\);
- \(C_{it}=1\) when a verified contract for \(i\), the same supplier's
  court-supported cartel interval, and year \(t\) have a common date;
- \(A_{it}=1\) when membership of \(i\) in an association, an affirmative
  exposure interval for that association, and year \(t\) have a common date.

This is an annual classification, not an ever-exposed indicator. Evidence in
one year does not change another year.

## Date and overlap rules

All intervals are inclusive. Input dates may use:

- `YYYY-MM-DD`;
- `YYYY-MM`, interpreted as the first day for a start and the last day for an
  end; or
- `YYYY`, interpreted as January 1 for a start and December 31 for an end.

A blank start or end creates an interval open in that direction. Both
boundaries cannot be blank because undated evidence cannot support a
municipality-year classification.

A rule applies to a year if all intervals required by that rule share at least
one actual day with the calendar year. Merely occurring somewhere in the same
year is insufficient. For example, a cartel period ending on March 31 and a
contract starting on April 1 do not produce exposure in that year.

Any positive within-year overlap produces the simple binary value `1`; the
pipeline does not prorate partial years. If a downstream model needs an
exposure fraction, such as months or days exposed, that should be constructed
as a separate variable rather than changing this indicator.

## Direct evidence

Every direct evidence row includes an `exposure_start` and `exposure_end`. A
court table that documents conduct in 2016 therefore supports 2016 only. When a
source lists non-contiguous years, the curated table uses separate rows so the
gap is not treated as covered.

An explicit direct zero sets coverage for its interval but does not override a
positive rule from another source.

## Contract rule

A contract is positive only when these three intervals have a common date:

1. the municipality–supplier contract;
2. a legally supported infringement period for the same `participant_id`;
3. the calendar year.

The participant roster is deliberately narrow and participant-specific.
Industry-wide cartel dates are not assigned to a firm unless a decision or
similarly authoritative source supports that firm's period.

A verified contract sets `data_found=true` in every year it covers even when
the supplier has no matching cartel period. A participant-period row by itself
does not provide municipality-level coverage.

## Association rule

An association rule requires a common date among:

1. the municipality's membership interval;
2. an evaluated exposure interval for that association;
3. the calendar year.

Current membership is never projected backward. An association finding also is
not propagated to municipalities for which no dated membership record exists.
An evaluated negative association interval can support `data_found=true` and
`exposure=0` for overlapping member-years.

## `data_found`

`data_found` records evidence coverage for a specific GKZ-year, not treatment:

- a direct row sets it for the years that row covers;
- a contract row sets it for the years the contract covers;
- an association membership sets it only for years in which it overlaps at
  least one evaluated row for that association.

Therefore:

| exposure | data_found | Interpretation |
|---:|:---:|---|
| 1 | true | At least one annual exposure rule is positive |
| 0 | true | Evidence covers the year but no positive rule is met |
| 0 | false | No coded evidence covers the municipality-year; zero is a default |
| 1 | false | Impossible by construction |

Default zeroes should normally be treated as unknown coverage, not clean
controls.

## Conflict and precedence

Positive evidence wins within a municipality-year. A zero in one source does
not erase a positive direct, contract, or association rule. The audit table
preserves:

- each rule-specific positive flag;
- the positive source IDs;
- direct and contract row counts for the year; and
- the number of evaluated association membership/exposure pairs.

This permits sensitivity analyses that use only one evidence channel or review
conflicting records.

## Territorial consistency

The default panel is balanced on the 2024 municipality universe. The fixed
geography makes row completeness transparent and supports merges to fiscal or
demographic data already harmonized to 2024 boundaries.

It does not imply that all 2024 units existed unchanged from 2001 onward.
Evidence using an obsolete or predecessor GKZ must be explicitly crosswalked
to the 2024 analysis unit before curation. The pipeline rejects evidence GKZ
values outside the selected universe rather than guessing a merger mapping.

A contemporaneous-boundary design would require annual municipality universes,
validity intervals, and a complete merger/split crosswalk. It would no longer
be the balanced fixed-geography panel produced here.

## Identification warning

This variable is a reproducible evidence classification, not by itself a causal
identification strategy. In particular:

- observed cartel-period contracts may be endogenous to customer allocation or
  bid rigging;
- published court project lists are examples and need not enumerate every
  affected municipality;
- `data_found=false` is non-random because procurement and association records
  are fragmented;
- a binary annual overlap does not measure affected contract value, waste
  volume, service share, or cartel intensity.

For causal work, consider:

- restricting the main specification to `data_found=true` and separately
  reporting the loss of coverage;
- treating `data_found=false` observations as unknown rather than confirmed
  zeroes;
- direct-evidence-only, contract-only, and association-only robustness
  definitions;
- predetermined exposure based on genuinely pre-cartel relationships;
- contract- or tender-level analysis around the first post-cartel competitive
  retendering; and
- keeping the exposure panel separate from any post-2021 outcome used in the
  regression.

## Present coverage

The initial curated release contains dated municipal and association projects
from the published FCC decision, participant-specific infringement periods for
FCC and the Huber entities, and GVA Mödling memberships only where the official
history gives an entry date. It has no verified municipality–supplier contract
rows yet.

The current default build contains 50,232 rows, 23 exposed
municipality-years, and 23 rows with `data_found=true`. Those counts describe
the present source coding, not the true geographic reach of the cartel.
