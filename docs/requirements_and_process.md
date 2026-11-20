# Requirements and process

## Agreed decisions

| Area | Decision |
| --- | --- |
| Audience and cadence | Internal research analysts manually prepare a weekly draft briefing. The default report timezone is America/Chicago. |
| Target universe | US-listed ETFs. The initial pilot tracks approved product records for BlackRock, WisdomTree, and Global X. Reports show the issuer subset and the number of approved products. |
| Data available today | A one-off public SEC filing verified the local import path for one IVV observation. The shared pilot still has no approved recurring financial dataset or client CSV export. Demo data is synthetic. |
| Starting stack | Python, SQLite, a loopback browser workspace, Markdown, HTML and JSON manifests. Evidence, approvals and exact exports persist in SQLite. |
| Collection and cost | Analysts edit a curated source list in YAML and can check approved feeds on demand. A one-shot refresh supports an existing scheduler. Paid subscriptions, hosted models, and team deployment require a separate decision. |
| Analysis | Financial calculations use Decimal and explicit observation dates, scopes, currencies, and fee units. The evidence summary works offline. Model synthesis is optional and gated on a local evaluation. |

Country, product type, and issuer IDs define the tracked subset. Approved products can have hierarchical
strategy, issuer, asset-class, geography, and exposure tags. Filters match all selected tags and their
descendants. Investment geography is a separate field from listing country.

## Weekly analyst workflow

1. Review the enabled sources in `configs/pilot.yaml`. For each proposed source, record a named owner, the
   permission reference, permitted collection and retention, internal-report use, AI use, distribution rights,
   the fields available, and the known gaps. Source candidates and the bounded checks appear in
   [Source audit](source_audit.md).
2. Once data is approved, use `imports/templates/` to prepare local product, metric, and news inputs.
   Use stable product and record IDs. For financial observations, record the source locator, measurement
   date, currency, scope, unit, and revision. When the source supplies a publication or availability date,
   record it separately from first observation and fee effective dates.
3. Open `ui pilot_client` or run the applicable import commands and `doctor`. Check feed health and the rejected-row locations and the
   `review-list` queue. An ambiguous event needs a verified fund ID before acceptance. Review decisions
   preserve the candidate list and record the reviewer and reason. Lifecycle counts use approved product dates.
4. Run a briefing with the desired filters. For CLI runs, use `--end` for an exclusive end date and `--cutoff` for a
   recorded UTC cutoff. Check the tracked subset, missing and stale observations, source status, the
   evidence register, and the manifest. Use the report library to review and finalize the briefing.
5. Back up the SQLite database and retain the matching configuration through the approved internal storage
   process. Keep input exports, databases, credentials, and generated reports outside version control.
   See [Setup and commands](../README.md).

## Source registry and health

Each YAML entry has a stable `source_id`, enabled state, permission and retention settings, coverage notes,
and an update frequency. Use `purpose` to separate `news`, `product_identity`, `fund_metrics`, and
`actual_revenue`. An enabled source with a purpose needs an owner and a permission reference. The endpoint
is an optional HTTP(S) reference for analyst use and is required over HTTPS for enabled RSS entries. CSV imports use local files. Existing entries with
unspecified purpose retain their previous import compatibility.

Use `--source-id` for a product CSV with one verified identity source and supply an
`identity_evidence_id` such as a filing link on every row. Financial observations and news carry the source
ID on each row. The importer checks the source purpose and internal-report permission. Selecting
`metadata_only` on a news source retains evidence metadata and omits the article body. Scope the values
retained from a financial source to its documented permission.

`doctor` reports the latest attributable manual import per source as success, partial, failed, or
unrecorded, along with row counts. Unrecorded includes earlier imports that predate attribution. An
unreadable file or a row without a recognized source can be diagnosed at the file level. RSS status
shows the latest attempt and cursor state is preserved after a failed collection.
Removing a source stops future imports and retains its prior run and evidence references. Rights changes
call for a separate review of the archive.

## Financial and temporal rules

- The default reports use USD fund net assets and net expense ratios. Gross assets and class- or series-level
  figures require their own scope. Management fees, gross expense ratios, and net expense ratios remain
  separate measurements.
- Matched-cohort changes use the same eligible products at both dates. Group comparisons require a common
  asset measurement date at each endpoint under the default setting. Full tracked-universe snapshots
  show coverage. Changes in assets can reflect market movement, distributions, and investor activity.
  Net flow requires its own observation.
- Missing values remain unavailable and a documented zero remains zero. The annualized expense-based proxy
  uses fund net assets times net expense ratio. Actual realized issuer revenue requires a separate source.
- Reports use retrospective mode with a recorded observation cutoff. Last-run checkpoints are scoped
  to the current report definition and move only after a successful export. Finalized exports stay intact.
  Strict historical reconstruction of all prior knowledge remains a separate coverage goal.

Failure isolation, bounded resource use, and visible gaps are design requirements for each new source and
workflow. The current checks cover malformed CSV rows, failed feeds, archive revisions, rollback on
export errors, and local browser review. Remaining deployment and data checks are tracked in [Next milestones](next_milestones.md).
