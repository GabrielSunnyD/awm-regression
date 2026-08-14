# Source data

This directory is the reproducible evidence layer:

- `registry.csv` lists every official source URL, stable `source_id`, and
  acquisition policy;
- `curated/` contains narrow, reviewed propositions extracted from those
  sources plus participant aliases and contract review status;
- `review/` records accepted, pending, or excluded dispositions for ambiguous
  source entries;
- `downloads/` is created by `uv run awm-sources download` and stores exact
  snapshots for registry rows marked `download`;
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
Rows marked `citation_only` are skipped in both normal and refresh builds.

The four BWB participant pages are `citation_only` because automated requests
receive a Sucuri JavaScript challenge. Their precise URLs remain registered for
browser review, and each points to the downloadable BWB FAQ as a supporting
snapshot. Validation never reports those four pages as checksum-verified.

To add evidence:

1. add its official HTTPS URL, unique `source_id`, and acquisition fields to
   `registry.csv` (normally `acquisition_method=download`);
2. download and read the snapshot;
3. add only source-supported propositions and intervals to `curated/*.csv`;
4. validate, rebuild, and inspect the long panel, wide exposure matrix, and
   municipality-year audit.

Direct evidence must be dated. Current association membership is not projected
into an earlier cartel year. A participant must be final and regionally
eligible. A tender or generated TED match is not a contract: only a manually
accepted row with municipality, supplier, performance interval, reviewer, and
review date enters the normalized data.

The preliminary `regional_exposure.csv` channel is broader: a final,
source-backed state operating interval applies to every GKZ with that state
prefix. Its notes must distinguish the source propositions from the project's
regional-proxy assumption. Pending matters, addresses, facilities, and undated
current web pages cannot create a regional rule.

The panel-level post-raid rule is separate from municipality evidence. Since
the registered BWB and participant findings end the documented cartel in March
2021, all complete calendar years from 2022 onward are known non-exposed
periods for every GKZ. The audit records this coverage explicitly; 2021 is not
treated as a clean annual zero.

Statistics Austria's administrative-change ZIP is parsed automatically.
Deterministic historical GKZ chains resolve to 2024; splits require explicit
researcher selection.
