# Normalized raw inputs

Run `uv run awm-sources all` or `uv run awm-build` to generate:

- the harmonized 2024 `municipalities.csv` universe;
- `municipality_crosswalk.csv`, derived from official GKZ changes since 2002;
- five dated evidence tables consumed by the classifier; and
- `source_log.csv`, which carries registry and checksum provenance forward.

Generated CSVs are ignored by Git. Do not hand-edit them. Amend
`data/sources/registry.csv` or `data/sources/curated/*.csv`, then rebuild.

The annual classifier requires dates on every evidence channel. Undated rows
fail rather than being applied to all 24 panel years. `contracts.csv` contains
only manually accepted reviews; procurement candidates never enter this
directory directly.
