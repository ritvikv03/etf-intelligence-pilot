# Requirements and process

## Agreed decisions

| Area | Decision |
| --- | --- |
| Audience and cadence | Internal research analysts manually prepare a weekly draft briefing. The default report timezone is America/Chicago. |
| Target universe | US-listed ETFs. The initial pilot tracks approved product records for BlackRock, WisdomTree, and Global X. Reports show the issuer subset and the number of approved products. |
| Data available today | There is no approved financial dataset or recurring client CSV export. Demo data is synthetic. Public samples are recorded as source candidates. |
| Starting stack | Python, SQLite, Markdown and HTML draft reports, and JSON manifests. Evidence and provenance persist in SQLite. |
| Collection and cost | Analysts edit a curated source list in the client YAML. Initial execution uses local files. Paid subscriptions, hosted models, scheduling, and deployment are deferred. |
| Analysis | Financial calculations use Decimal and explicit observation dates, scopes, currencies, and fee units. Evidence-linked qualitative synthesis is a later capability. Any AI synthesis will be optional and evaluated independently. |

Country, product type, and issuer IDs currently define the tracked subset. Hierarchical strategy, asset-class,
and geographic filters belong to the taxonomy milestone. Asset-class settings in the current YAML describe
the intended coverage.

## Weekly analyst workflow

1. Review the enabled sources in `configs/pilot.yaml`. For each proposed source, record a named owner, the
   permission reference, permitted collection and retention, internal-report use, AI use, distribution rights,
   the fields available, and the known gaps. Source candidates and the bounded checks appear in
   [Source audit](source_audit.md).
2. Once data is approved, use `imports/templates/` to prepare local product, metric, and news inputs.
   Use stable product and record IDs. For financial observations, record the source locator, measurement
   date, currency, scope, unit, and revision. When the source supplies a publication or availability date,
   record it separately from first observation and fee effective dates.
3. Run `init`, the applicable import commands, and `doctor`. Review the rejected-row locations and the
   `review-list` queue. An ambiguous event needs a verified fund ID before acceptance. Review decisions
   preserve the candidate list and record the reviewer and reason. Lifecycle counts use approved product dates.
4. Run `report pilot_client weekly`. Use `--end` for an explicit exclusive end date and `--cutoff` for a
   recorded UTC cutoff. Check the tracked subset, missing and stale observations, source status, the
   evidence register, and the manifest before sharing a draft internally.
5. Back up the SQLite database and retain the matching configuration through the approved internal storage
   process. Keep input exports, databases, credentials, and generated reports outside version control.
   See [Setup and commands](../README.md).

The registry currently accepts enabled `manual_import` sources with a permission reference. Removing
a source stops future imports and retains the source record for the evidence already archived. Rights
changes require reviewing the permitted use and retention of that archive.

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
- Reports use the retrospective mode. Observation cutoff and manual reviews have different time semantics.
  Finalization, frozen checkpoints, and `as_known_then` mode require further implementation.

Failure isolation, bounded resource use, and visible gaps are design requirements for each new source and
workflow. The current checks cover malformed CSV rows and local CLI execution. Limits for downloads,
transient faults, archive size, and cross-source failures are tracked in [Next milestones](next_milestones.md).
