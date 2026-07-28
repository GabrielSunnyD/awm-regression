# Austrian waste-cartel municipality exposure

This project builds a simple, auditable municipality-level exposure indicator
for every Austrian municipality:

```text
gkz,exposure,data_found
```

`exposure=1` when at least one reviewed source supports direct municipal
exposure, a municipality contract overlaps a participant's court-supported
infringement period, or association membership overlaps a reviewed association
exposure. Positive evidence wins when rules conflict.

## Reproduce the data

Install [`uv`](https://docs.astral.sh/uv/), clone the repository, and run:

```bash
uv sync --locked
uv run awm-sources all
uv run awm-exposure
```

The first command creates the locked project environment. `awm-sources` then
downloads official evidence to `data/sources/downloads`, records SHA-256
checksums, and builds the six normalized files in `data/raw`. `awm-exposure`
writes:

- `data/processed/municipality_exposure.csv` — requested simple output;
- `data/processed/municipality_exposure_audit.csv` — rule flags, counts, and
  positive source IDs.

Use `uv run awm-sources all --refresh` only when you intentionally want to
replace cached source snapshots with the latest server copies. Changed
checksums are recorded in `data/sources/download_manifest.json`.

Run the test suite with:

```bash
uv run python -m unittest discover -s tests -v
```

## Evidence architecture

The project keeps three layers separate:

1. `data/sources/registry.csv` defines official URLs and stable citation IDs.
2. `data/sources/curated/*.csv` records propositions a researcher actually
   reviewed in those sources.
3. Generated `data/raw/*.csv` contains GKZ-normalized inputs for the exposure
   classifier.

Statistics Austria's 2026 SHAPE-ZIP supplies the official municipality
universe. The source builder reads only its identifier and name attributes and
collapses the WFS service's 23 Vienna district geometries to municipality GKZ
`90001`, yielding the national municipality universe.

Court documents are not classified with unrestricted place-name matching.
Legal decisions contain company addresses, project locations, anonymized firms,
and other incidental place names that are not proof of municipal exposure.
Reviewed records therefore preserve the exact source ID and a concise coding
reason. The same conservative rule applies to procurement: a notice is not
entered as a municipality contract unless it identifies both the contracting
municipality and supplier.

## Interpretation and current limits

`data_found` measures evidence coverage, not treatment:

- `exposure=1, data_found=true`: at least one positive rule was met;
- `exposure=0, data_found=true`: some relevant evidence was evaluated but did
  not meet a positive rule;
- `exposure=0, data_found=false`: no coded evidence was available, so zero is a
  default.

The last category must not be read as affirmative proof that a municipality was
unexposed. Historical procurement data and waste-association membership remain
fragmented, and the current `contracts.csv` is intentionally empty until
municipality–supplier awards can be verified. See
[`docs/data_sources.md`](docs/data_sources.md) for the collection workflow and
[`docs/methodology.md`](docs/methodology.md) for the classification rules and
identification cautions.

