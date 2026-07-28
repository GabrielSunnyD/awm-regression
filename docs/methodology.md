# Methodology

## Estimand encoded by this file

The main output is a municipality-level **ever-exposed** classification. For
municipality \(i\):

\[
E_i = \max(D_i, C_i, A_i),
\]

where:

- \(D_i=1\) for direct affirmative evidence;
- \(C_i=1\) for a contract whose interval overlaps a legally supported cartel
  interval for the same participant ID;
- \(A_i=1\) for association membership overlapping an affirmative association
  exposure interval.

An interval with a blank start or end is open in that direction. A year-only
start is interpreted as January 1, while a year-only end is December 31.

## `data_found`

`data_found` records evidence coverage, not treatment:

- any direct evidence row sets it to true;
- any contract row sets it to true, whether or not the supplier and dates
  produce exposure;
- association membership sets it to true only if the association has at least
  one evaluated row in `association_exposure.csv`.

Thus:

| exposure | data_found | Interpretation |
|---:|:---:|---|
| 1 | true | At least one rule finds exposure |
| 0 | true | Evidence was reviewed but no positive rule was met |
| 0 | false | No exposure-relevant evidence was available; zero is a default |
| 1 | false | Impossible by construction |

## Conflict and precedence rules

Positive evidence wins. An explicit zero in one source does not override a
positive contract or association rule. The audit file retains rule-specific
flags and positive source IDs, so conflicts can be reviewed outside the simple
main output.

## Territorial consistency

Use one municipality universe and record its reference date. Evidence GKZ values
that do not occur in that universe cause the build to fail. Historical municipal
mergers therefore require a deliberate crosswalk before building a current-GKZ
output.

If the regression spans years with changing boundaries, consider building a
separate historical crosswalk or a municipality-year dataset. The current
pipeline intentionally does not guess how predecessor municipalities should map
to successors.

## Identification warning

This variable is a reproducible classification, not by itself an identification
strategy. Contract-based exposure can be endogenous if contracts observed during
the cartel period are themselves affected by allocation or bid-rigging.
For causal work, preserve the rule flags and consider:

- reporting results with and without default-zero (`data_found=false`) units;
- a direct-evidence-only robustness definition;
- predetermined exposure based on pre-cartel relationships;
- contract- or tender-level analysis around the first post-cartel retendering.

