# Regression outputs

Running `uv run awm-regress` writes four ignored analysis artifacts here by
default:

- `regression_results.csv`: coefficient estimates, standard errors, test
  statistics, p-values, and confidence intervals;
- `regression_sample.csv`: the exact complete-case estimation sample plus
  within-transformed outcomes, fitted values, and residuals;
- `regression_metadata.json`: input paths, model choices, drop counts, sample
  dimensions, degrees of freedom, and estimation diagnostics; and
- `regression_summary.txt`: a compact human-readable model summary.

These files are generated from the researcher-supplied long regression input
and are not committed. See [`../../docs/regression.md`](../../docs/regression.md)
for the input schema and interpretation.
