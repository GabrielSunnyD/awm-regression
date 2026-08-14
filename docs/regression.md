# Fixed-effects expenditure regression

## Estimand

The analysis command estimates

\[
Y_{it}=\beta E_{it}+X_{it}'\gamma+\alpha_i+\lambda_t+\varepsilon_{it},
\]

where (Y_{it}) is expenditure for municipality (i) in year (t), (E_{it})
is the project's municipality-year exposure indicator, (X_{it}) contains the
time-varying controls supplied by the researcher, (alpha_i) is a GKZ fixed
effect, and (lambda_t) is a year fixed effect. The reported exposure
coefficient is (hat\beta).

GKZ fixed effects absorb stable differences across municipalities. Year fixed
effects absorb shocks common to all municipalities in a year. The default
standard errors are clustered by GKZ so arbitrary serial correlation and
heteroskedasticity are allowed within a municipality. `--cluster gkz-year`
uses two-way GKZ and year clustering as a robustness option.

The software estimates the stated model; it cannot by itself make
(hat\beta) causal. A causal interpretation additionally requires that,
conditional on the controls and fixed effects, changes in exposure are not
driven by unobserved municipality-specific expenditure shocks. It also
requires appropriate timing, no relevant spillovers, and correctly measured
exposure, expenditure, and controls. Pre-trend or event-study evidence should
be evaluated separately before describing the result as a cartel effect.

## Inputs

### Exposure panel

The default exposure input is the existing long output:

```text
data/processed/municipality_year_exposure.csv
```

This file now uses the preliminary regional specification: the union of
direct, accepted-contract, dated-association, and final source-backed state
operating-presence channels. A regional positive means that operating presence
was applied to every GKZ in a supported state; it does not establish a
municipal contract or damages. Inspect the audit's separate channel flags,
compare against the narrow three-channel indicators, and do not estimate this
model if the exposure CLI warns that the broad indicator is absorbed by GKZ or
year fixed effects.

It contains one row per key with:

```text
gkz,year,exposure_direct,exposure_regional,exposure,exposure_basis,data_found,data_found_direct,data_found_regional
```

The default `--exposure-column exposure` uses the union. Select
`exposure_direct` or `exposure_regional` explicitly for robustness analysis.
Each selection uses its matching `data_found*` flag, preventing evidence for
one component from turning an unknown zero in the other into a clean control.
The loader also accepts the legacy four-column panel and validates the union
identity whenever all three exposure columns are present.

By default, only `data_found=true` rows are eligible for estimation. The
exposure pipeline defines `data_found=false, exposure=0` as unknown evidence
coverage, not a verified unexposed control. Use `--include-unknown-exposure`
only for a deliberate alternative specification that treats those default
zeroes as usable. If the exposure CSV has no `data_found` column, that option
is required.

### Regression input CSV

Expenditure and time-varying controls are supplied together in one long CSV
with one row per GKZ-year:

```csv
gkz,year,expenditure,population,unemployment_rate
10101,2001,125000.00,1520,0.041
10101,2002,129500.00,1542,0.039
10102,2001,98000.00,1180,0.052
```

Requirements:

- the key columns are named exactly `gkz` and `year`;
- the outcome column is named exactly `expenditure`;
- every additional column is treated as a time-varying control and its header
  becomes the coefficient name;
- each GKZ-year appears at most once;
- `year` uses four digits;
- expenditure and control cells are plain finite numbers using a decimal point,
  or blank/missing; and
- GKZ values with one to five digits are zero-padded to five digits during the
  join.

An empty expenditure or control cell means that the variable was not found for
that GKZ-year. Complete-case analysis excludes the entire row if expenditure or
any control is missing. A numeric `0` is not missing: it is retained as the
actual value zero. The recognized explicit missing tokens are `.`, `NA`, `N/A`,
`NaN`, and `null`, without regard to letter case. A missing `gkz` or `year` is a
schema error because the row cannot be identified.

The command does not deflate, winsorize, scale, or otherwise reinterpret these
amounts. Supply expenditure in the units and price basis appropriate for the
research design. The default level model reports the coefficient in those
units. `--log-outcome` instead estimates `log(expenditure)` and therefore
requires every included amount to be strictly positive; consequently, a real
zero expenditure is valid in the level model but invalid in the log model.

Controls are optional: a file containing only `gkz`, `year`, and `expenditure`
estimates an exposure-only fixed-effects specification. When controls are used,
transformations such as logs, per-capita values, or lags must be created in
this input CSV and named clearly.

An editable example is available at
[`data/input_templates/regression_input.csv`](../data/input_templates/regression_input.csv).

## Run the model

After building the exposure panel:

```bash
uv sync --locked
uv run awm-regress \
  --input-csv path/to/regression_input.csv
```

The exposure path and output directory can be overridden:

```bash
uv run awm-regress \
  --exposure-csv data/processed/municipality_year_exposure.csv \
  --input-csv path/to/regression_input.csv \
  --output-dir data/regression \
  --start-year 2001 \
  --end-year 2024 \
  --cluster gkz
```

Useful deliberate alternatives include:

```bash
# Semi-log outcome; expenditures must be positive
uv run awm-regress --input-csv path/to/regression_input.csv --log-outcome

# Two-way GKZ/year clustered standard errors
uv run awm-regress --input-csv path/to/regression_input.csv --cluster gkz-year

# Sensitivity analysis that admits unknown-coverage exposure zeroes
uv run awm-regress \
  --input-csv path/to/regression_input.csv \
  --include-unknown-exposure
```

## Sample construction

The command applies these rules in order:

1. restrict to `--start-year` and `--end-year`, when supplied;
2. exclude unknown exposure coverage unless explicitly included;
3. require a matching row in the regression input;
4. require nonmissing expenditure and every supplied control, retaining
   numeric zeroes; and
5. iteratively remove GKZ or year fixed-effect groups represented by only one
   remaining observation.

It then removes GKZ and year means through iterative two-way residualization,
which is valid for unbalanced panels. The model fails rather than silently
dropping a regressor when exposure or controls are collinear after fixed
effects. The JSON metadata records mutually exclusive drop counts, fixed-effect
rank, connected components, residual degrees of freedom, cluster counts, and
the residualization iteration count.

## Outputs

The default `data/regression/` directory receives:

| File | Purpose |
|---|---|
| `regression_results.csv` | Estimates and inference for exposure and each control |
| `regression_sample.csv` | Exact estimation rows and within-model residual diagnostics |
| `regression_metadata.json` | Reproducible specification, sample construction, and numerical diagnostics |
| `regression_summary.txt` | Compact console-style summary |

In the level model, the exposure estimate is the conditional change in
expenditure units associated with `exposure` changing from 0 to 1. In the log
model it is a log-point change; the exact percentage equivalent for a binary
indicator is (100[\exp(\hat\beta)-1]). Always interpret the estimate together
with its uncertainty, sample coverage, and identifying assumptions.
