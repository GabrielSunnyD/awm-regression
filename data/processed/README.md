# Processed outputs

Running `uv run awm-build` or `uv run awm-exposure` writes:

- `municipality_year_exposure.csv` with
  `gkz,year,exposure,data_found`;
- `municipality_year_exposure_wide.csv` with one row per GKZ and columns
  `gkz,municipality_name,2001,...,2024`; and
- `municipality_year_exposure_audit.csv` with municipality names, annual rule
  flags, data-coverage reasons, evidence counts, and positive source IDs.

The default long build is sorted by `gkz,year` and contains one row for every
2024 GKZ in every year from 2001 through 2024. The wide file contains exposure
only; use the long file to retain `data_found`. Generated CSVs are ignored by
Git.
