# Source data

This directory separates evidence acquisition from the generated `data/raw`
tables:

- `registry.csv` lists every official source URL and its stable `source_id`.
- `curated/` contains reviewed, source-backed propositions extracted from those
  documents.
- `downloads/` is created by `uv run awm-sources download` and stores the exact
  downloaded snapshots.
- `download_manifest.json` records access times, byte sizes, and SHA-256
  checksums.

Downloaded files and the generated manifest are ignored by Git because they can
be reproduced from the registry. Curated records are committed because legal
documents cannot be converted safely by unreviewed place-name matching.

To add evidence:

1. Add its official URL and a unique `source_id` to `registry.csv`.
2. Run `uv run awm-sources download`.
3. Review the source and add only propositions it actually supports to the
   appropriate `curated/*.csv`.
4. Run `uv run awm-sources build`.
5. Inspect `data/raw/source_log.csv` and then run `uv run awm-exposure`.

Current association membership is not automatically projected into an earlier
cartel year. Add a membership interval only when an official historical source
supports it. Likewise, a tender notice is not treated as an awarded contract
unless the source identifies both the contracting municipality and supplier.

