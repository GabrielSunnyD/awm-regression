# Procurement review queue

Run:

```bash
uv run awm-ted
```

This generates `procurement_candidates.csv` and a metadata JSON file. Every row
starts as `review_status=pending`. The files are ignored by Git because they are
reproducible API output, not accepted evidence.

Do not edit the generated queue into treatment. Review the underlying TED
notice and confirm:

1. the buyer is a municipality (not merely an association, firm, or location);
2. the notice records an actual award to the matched participant;
3. the service is relevant municipal waste work;
4. the performance start and end dates are supported; and
5. the municipality can be resolved to the intended 2024 GKZ.

Then register and download the notice source, and copy the reviewed facts to
`data/sources/curated/contracts.csv` with `review_status=accepted`, a reviewer,
and a review date. Pending and rejected curated rows never enter
`data/raw/contracts.csv`.
