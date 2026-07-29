# Processed outputs

Running `uv run awm-build` or `uv run awm-exposure` writes:

- `municipality_year_exposure.csv` with
  `gkz,year,exposure,data_found`; and
- `municipality_year_exposure_audit.csv` with municipality names, annual rule
  flags, evidence counts, and positive source IDs.

The default build is sorted by `gkz,year` and contains one row for every 2024
GKZ in every year from 2001 through 2024. Generated CSVs are ignored by Git.
