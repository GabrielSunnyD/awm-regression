# AGENTS.md

## Scope and instruction priority

This file applies to the entire repository. Follow an `AGENTS.md` or
`AGENTS.override.md` in a more specific subdirectory when one exists. Direct
instructions in the current task take priority over this file.

This repository is a research pipeline, not only a software package. A change
is complete only when the implementation, evidence inputs, generated-data
semantics, tests, and documentation agree.

## Project purpose

The project builds an auditable Austrian municipality-year panel describing
exposure to the Austrian waste-management cartel and estimates fixed-effects
models of municipal expenditure on that exposure.

The canonical panel unit is a five-digit Austrian municipality code (`gkz`) by
calendar year. The default years are 2001-2024 and the current geographic
universe is Statistics Austria's municipality geography at 2024-01-01.

Treat the exposure output as a source-backed research classification. It is
not, by itself, proof of damages, cartel intensity, or causal identification.

## Start every task by orienting

Before editing:

1. Read `README.md` and the relevant document under `docs/`.
2. Inspect `git status` and preserve unrelated user changes.
3. Identify whether the task changes software behavior, evidence coding,
   generated outputs, regression semantics, or some combination.
4. Trace the relevant CLI through `src/awm_exposure/` before changing wrappers
   under `scripts/`.
5. State any methodological assumption that is not already fixed by the task.

Do not infer the current methodology solely from old output counts or filenames.
The implementation, curated inputs, tests, and current documentation must be
read together.

## Environment and package management

- Use Python 3.12 or a compatible version declared in `pyproject.toml`.
- Use `uv` for dependency management and command execution.
- Run `uv sync --locked` to reproduce the checked-in environment.
- Run project commands as `uv run ...`; do not substitute system Python,
  `pip install`, Conda, Poetry, or a hand-created virtual environment in project
  documentation.
- Prefer the standard library and existing dependencies. Add a production
  dependency only when it materially simplifies or improves a required feature.
- If dependencies change, update both `pyproject.toml` and `uv.lock`, explain
  the reason, and run `uv lock --check`.
- Never add credentials, tokens, private URLs, or machine-specific paths to the
  repository.

## Repository map

- `src/awm_exposure/sources.py`: source registry validation, acquisition,
  checksums, and normalization into `data/raw/`.
- `src/awm_exposure/pipeline.py`: municipality-year exposure construction and
  audit output.
- `src/awm_exposure/regression.py`: fixed-effects regression and estimation
  sample construction.
- `src/awm_exposure/ted.py`: review-only TED procurement-candidate discovery.
- `src/awm_exposure/*_cli.py`: public command-line interfaces.
- `scripts/`: thin convenience entry points; core logic belongs in the package.
- `data/sources/registry.csv`: stable source IDs, URLs, and acquisition policy.
- `data/sources/curated/`: researcher-reviewed propositions used by builders.
- `data/sources/review/`: explicit dispositions for ambiguous evidence.
- `data/input_templates/`: user-editable input schemas.
- `data/raw/`: generated normalized classifier inputs.
- `data/processed/`: generated exposure panels and audits.
- `data/review/`: generated candidates awaiting human review.
- `data/regression/`: generated estimation outputs.
- `tests/`: `unittest` coverage for sources, exposure, TED, and regression.
- `docs/data_sources.md`: acquisition and evidence-ingestion runbook.
- `docs/methodology.md`: exposure definitions and identification cautions.
- `docs/regression.md`: regression input, estimation, and output semantics.

## Non-negotiable data conventions

### Municipality identifiers

- Treat GKZ as a string, not an integer.
- Normalize valid codes to exactly five digits without losing leading zeroes.
- Never infer a municipality from a partial or fuzzy name match when exposure
  would change as a result.
- Resolve historical codes through the official crosswalk. Do not automatically
  copy evidence across a one-to-many split; require explicit review.
- Remember that the fixed-2024 geography is a harmonized estimand, not a claim
  that every current municipality existed unchanged in every historical year.

### Dates and intervals

- Intervals are inclusive.
- Preserve the documented precision of a source. Expand `YYYY` to the full
  calendar year and `YYYY-MM` to the full month only according to the existing
  parser rules.
- Require at least one shared calendar day when intersecting a year, contract,
  participant period, membership, association period, or regional period.
- Do not treat two non-overlapping intervals in the same year as overlapping.
- Do not substitute publication, decision, award, or retrieval dates for a
  service-performance interval without explicit source support.

### Missing values and zeroes

- A blank regression value means the observation was not found and is missing.
- Numeric zero is a real observed value and must remain in level specifications.
- Exclude a GKZ-year from regression when expenditure or any requested control
  is missing, following the documented complete-case rule.
- `exposure=0, data_found=false` means unknown coverage, not verified
  non-exposure. Never silently recode it as a clean control.
- `exposure=1, data_found=false` is invalid.

## Evidence and source standards

Every exposure-affecting proposition must be traceable to real evidence.

1. Prefer primary official sources: court decisions, competition-authority
   material, legislation, official municipality or association records,
   Statistics Austria, and official procurement notices.
2. Use secondary material for discovery or context, not as the sole basis for a
   municipality-year treatment assignment when a primary source is available.
3. Register each relied-upon source in `data/sources/registry.csv` with a stable,
   descriptive `source_id` and an HTTPS URL.
4. Prefer `acquisition_method=download` with a reproducible snapshot, format
   check, manifest entry, byte size, and SHA-256 hash.
5. Use `citation_only` only when a source was genuinely reviewed but normal HTTP
   acquisition is blocked. It must point to a registered downloadable supporting
   snapshot, and the notes must identify which claim depends on the uncached page.
6. Do not bypass anti-bot controls, authentication, paywalls, or access rules.
7. Record the narrow proposition actually supported, including entity,
   geography, dates, status, source location, and uncertainty. Do not turn a
   vague statement into false precision.
8. Distinguish source text, researcher inference, and project assumption in
   notes and documentation.
9. Never fabricate a municipality, contract, participant, interval, regional
   scope, citation, quotation, checksum, or review decision.
10. An absence from selective court or procurement records is not evidence of
    non-exposure.

When a source conflicts with an existing curated row, stop and surface the
conflict. Do not silently choose the value that produces the desired estimate.

## Exposure-rule design

The existing classifier may contain several evidence channels, including
direct municipality findings, accepted contracts, and association membership.
A task may deliberately introduce a broader preliminary definition, such as
regional exposure. Implement such changes transparently rather than erasing
the distinction between stronger and weaker evidence.

For every exposure channel:

- define its unit, geography, time interval, eligibility gates, and annual
  overlap rule;
- retain the supporting `source_id` values in the audit;
- expose a channel-specific audit flag or reason;
- ensure any positive channel implies `data_found=true`;
- combine channels deterministically, normally as an explicit maximum/OR rule;
- keep output ordering stable; and
- add positive, negative, boundary, and contradiction tests.

### Regional exposure

If regional presence is allowed to assign exposure to all GKZs in an area:

- label it as a broad or preliminary proxy, not direct municipality evidence;
- require a source-backed geographic unit such as a federal state, district,
  association territory, or explicitly documented service area;
- require a source-backed operating or infringement interval;
- map the region to GKZs using an explicit, reviewable rule;
- do not infer operating scope from a company address, facility address, place
  of incorporation, isolated project, or undated current website;
- do not expand a district reference to a state or a state reference to all of
  Austria;
- preserve stronger direct, contract, and association indicators separately in
  the audit even if the public `exposure` column is their union;
- report how many municipalities and municipality-years each region rule adds;
  and
- test whether the resulting exposure retains within-year and within-GKZ
  variation after fixed effects. Warn clearly if it is absorbed by year or GKZ
  fixed effects or leaves no usable comparison group.

If the task changes the substantive definition of exposure, update the
methodology, README, audit schema, tests, and relevant input template together.
Prefer a named specification or channel over silently changing the meaning of
an existing field when users may need to compare narrow and broad estimates.

### Legal and review gates

- Preserve the distinction between final findings and pending/admitted matters.
- A pending participant must not trigger exposure unless the task explicitly
  changes that policy and the outputs label the alternative clearly.
- TED matches are candidates only. They cannot affect exposure until the award,
  municipal buyer, relevant service, participant, performance dates, source,
  reviewer, and review date are accepted in curated data.
- A current association membership must not be projected backward without dated
  legal or official support.
- Preserve the full post-raid invariant unless the documented cartel end date
  or annual rule is deliberately revised with source support. A contradiction
  should fail loudly rather than be overwritten.

## Source-ingestion workflow

To add or change evidence:

1. Register the source.
2. Acquire or explicitly classify it under the registry policy.
3. Validate the snapshot and manifest.
4. Read the source and record only supported curated propositions.
5. Normalize through the builder; never hand-edit normalized outputs.
6. Build the exposure panel.
7. Inspect the affected audit rows and aggregate counts.
8. Run the source, pipeline, and full regression test suite as applicable.
9. Update the methodology and source documentation.

Useful commands:

```bash
uv run awm-sources download
uv run awm-sources validate
uv run awm-sources build
uv run awm-exposure
uv run awm-build
uv run awm-build --offline
uv run awm-ted
```

Use `--refresh` only when intentionally replacing reviewed snapshots. Do not
make a routine build depend on mutable live pages when a checksum-verified cache
is expected.

## Generated files and editing boundaries

- Do not hand-edit files under `data/raw/`, `data/processed/`,
  `data/regression/`, or generated candidate files under `data/review/`.
- Make evidence changes in `data/sources/registry.csv`,
  `data/sources/curated/`, or `data/sources/review/`, then regenerate.
- Respect `.gitignore`. Do not commit downloaded snapshots, manifests, generated
  panels, regression results, caches, or candidate outputs unless the task
  explicitly changes the repository's data-retention policy.
- Keep generation deterministic: stable row order, stable field order, explicit
  encodings, atomic writes, and no network calls at import time.
- Never overwrite a researcher-supplied regression input CSV.

## Regression safeguards

The standard model is expenditure on exposure and supplied time-varying
controls with GKZ and year fixed effects and GKZ-clustered standard errors.

- Preserve the exact `gkz`, `year`, and `expenditure` input names unless a task
  explicitly changes the public schema.
- Treat every additional input column as a control only under the documented
  interface.
- Preserve complete-case filtering and the distinction between blank and zero.
- Do not silently deflate, winsorize, log, scale, lag, or convert to per-capita
  values.
- Fail on duplicate keys, invalid numbers, invalid log outcomes, collinearity,
  rank failure, or insufficient clusters rather than silently repairing data.
- Keep the exact estimation sample and drop reasons reproducible in outputs.
- Do not describe a coefficient as causal merely because fixed effects were
  included. Report coverage, identifying variation, uncertainty, potential
  spillovers, selection into observed evidence, and relevant pre-trend checks.
- When exposure becomes broader, explicitly compare identification and sample
  variation against the narrower definition.

## Implementation conventions

- Keep core behavior in `src/awm_exposure/`; scripts should remain thin.
- Prefer small, typed, deterministic functions with explicit inputs and outputs.
- Use `pathlib.Path`, UTF-8, `csv.DictReader`/`DictWriter`, and existing atomic
  write patterns consistently.
- Validate at system boundaries and raise actionable domain-specific errors.
- Preserve CLI compatibility unless the task requires a breaking change. If a
  flag, default, schema, or output changes, update help text and documentation.
- Avoid hidden global state and network-dependent tests.
- Mock HTTP in unit tests. Tests must not depend on live government sites.
- Add comments for legal, geographic, or econometric reasoning; do not add
  comments that merely restate Python syntax.
- Keep source and research-policy decisions visible in data and documentation,
  not buried as unexplained constants.

## Required validation

Run targeted tests while developing. Before handing off a software or evidence
change, run:

```bash
uv lock --check
uv run python -m compileall -q src scripts
uv run python -m unittest discover -s tests -v
```

Additionally:

- Source or curated-data changes: run `uv run awm-sources validate` and
  `uv run awm-build --offline` once verified snapshots exist.
- Downloader changes: test fresh-download, cached, offline, citation-only, bad
  content, checksum mismatch, redirect, and atomic-failure paths with mocks.
- Exposure changes: inspect long, wide, and audit outputs; verify row counts,
  uniqueness, year bounds, `exposure`/`data_found` invariants, channel counts,
  and interval boundaries.
- Regression changes: test coefficient recovery, missing-versus-zero behavior,
  fixed-effect singleton removal, rank checks, clustering, and metadata counts.
- CLI changes: run the affected `--help` command and at least one end-to-end
  invocation.
- Documentation-only changes: verify commands, filenames, schemas, links, and
  stated counts against the current code and build.

If a check cannot run because an official source is unavailable, distinguish a
network limitation from a code failure. Report exactly what ran, what did not,
and whether a checksum-verified offline build was possible.

## Documentation requirements

Keep these synchronized with behavior:

- `README.md` for user workflow, headline methodology, commands, and current
  output summary;
- `docs/data_sources.md` for acquisition, validation, schemas, and review;
- `docs/methodology.md` for exposure definitions, geography, dates, coverage,
  audit semantics, and identification cautions;
- `docs/regression.md` for model, inputs, filtering, inference, and outputs;
- CLI `--help` text for executable behavior; and
- `data/input_templates/` for accepted user schemas.

Do not update a generated count by estimation or manual arithmetic when the
pipeline can compute it. Regenerate, inspect, and state which specification the
count describes.

## Git and handoff discipline

- Keep changes focused and preserve unrelated work.
- Do not force-push, rewrite history, delete branches, or use destructive Git
  commands unless explicitly requested.
- Do not commit or open a pull request unless the task requests publication.
- Before a requested commit, inspect the diff and include only intended files.
- A handoff or pull-request summary must state:
  - what behavior or evidence changed;
  - the source-backed methodological rationale;
  - affected schemas and outputs;
  - exact validation commands and results;
  - material output-count changes;
  - identification risks or unresolved review items; and
  - any step that still requires a human researcher.

Favor reproducibility and honest uncertainty over a larger exposure count or a
more favorable regression result.
