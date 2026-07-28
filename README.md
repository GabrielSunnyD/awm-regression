# Austrian Waste Management Cartel exposure

This repository builds a municipality-level **ever-exposed** indicator for the
Austrian waste-management cartel.

The official abbreviation is **GKZ** (*Gemeindekennziffer*), not GZK. The main
output has one row per municipality:

```text
gkz,exposure,data_found
10101,1,true
10102,0,false
```

`exposure = 1` when at least one of the following rules is satisfied:

1. a coded source explicitly identifies the municipality as exposed;
2. the municipality had a contract with a cartel participant and the contract
   dates overlap that participant's legally supported cartel period; or
3. the municipality belonged to a waste-management association during a period
   for which that association is coded as exposed.

Otherwise `exposure = 0`. Positive evidence always wins if sources conflict.

`data_found = true` means at least one exposure-relevant observation was
available for the municipality: a direct coding row, a contract row, or
membership in an association whose exposure status was evaluated. It does **not**
mean that exposure was found. A municipality with no such evidence is assigned
`exposure = 0, data_found = false`, making default-zero cases distinguishable
from evidence-supported zeroes.

This produces a cross-section, despite the word "panel" sometimes being used
informally for the output. It does not create a municipality-year treatment
variable.

## Quick start

Python 3.10 or newer is sufficient; the pipeline has no third-party runtime
dependencies.

```bash
python scripts/build_exposure.py \
  --input-dir data/raw \
  --output-dir data/processed
```

The command writes:

- `data/processed/municipality_exposure.csv`: the requested three-column output;
- `data/processed/municipality_exposure_audit.csv`: rule flags, evidence counts,
  and positive source IDs used to check individual classifications.

Use `--omit-data-found` for a two-column main output or `--no-audit` to skip the
audit file.

Run the tests with:

```bash
python -m unittest discover -s tests -v
```

## Required and optional inputs

Place CSV files in `data/raw`. Copy the headers from `data/input_templates`.
All column names are lowercase.

| File | Required | Purpose |
|---|---:|---|
| `municipalities.csv` | yes | Complete municipality universe for a single territorial reference date |
| `direct_evidence.csv` | no | Municipality explicitly evaluated by a court document or another coded source |
| `cartel_periods.csv` | for contract rule | Legally supported infringement interval(s) for each participant |
| `contracts.csv` | no | Municipality-supplier contract observations |
| `association_exposure.csv` | for association rule | Exposure status and period of a waste-management association |
| `association_memberships.csv` | no | Municipality membership intervals in associations |

The exact schemas and recommended sources are documented in
[`docs/data_sources.md`](docs/data_sources.md). Dates may be `YYYY`,
`YYYY-MM`, or `YYYY-MM-DD`; blank interval endpoints are treated as open.

## Reproducibility choices

- GKZ values are read as strings, left-padded to five digits, validated, and
  sorted.
- Evidence containing a GKZ outside the municipality universe causes a hard
  error. This prevents silent mixing of territorial vintages.
- Firm and association joins use stable researcher-created IDs, not fuzzy name
  matching.
- Input evidence is never inferred from a municipality name alone.
- The audit output reports how each positive was generated.

The methodology is intentionally conservative and transparent. In particular,
`data_found = false` municipalities should not automatically be interpreted as
known untreated municipalities in a regression. See
[`docs/methodology.md`](docs/methodology.md).

