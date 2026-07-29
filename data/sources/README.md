# Source data

This directory is the reproducible evidence layer:

- `registry.csv` lists every official source URL and stable `source_id`;
- `curated/` contains narrow, reviewed propositions extracted from those
  sources;
- `downloads/` is created by `uv run awm-sources download` and stores exact
  snapshots;
- `download_manifest.json` records access times, byte sizes, and SHA-256
  checksums.

Downloads and the generated manifest are ignored by Git because they can be
recreated. Curated records are committed because legal interpretation cannot be
reproduced safely with unrestricted place-name matching.

The normal workflow is:

```bash
uv run awm-sources download
uv run awm-sources validate
uv run awm-sources build
uv run awm-exposure
```

Or run all stages with `uv run awm-build`. Use `awm-build --offline` to require
the existing verified cache and `--refresh` to intentionally replace snapshots.

To add evidence:

1. add its official HTTPS URL and a unique `source_id` to `registry.csv`;
2. download and read the snapshot;
3. add only source-supported propositions and intervals to `curated/*.csv`;
4. validate, rebuild, and inspect the municipality-year audit.

Direct evidence must be dated. Current association membership is not projected
into an earlier cartel year, and a tender notice is not treated as an awarded
contract unless the source identifies the contracting municipality, supplier,
and a defensible performance interval.
