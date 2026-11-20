# Data dictionary

- Timestamps: UTC ISO 8601 (`...Z`). Dates: `YYYY-MM-DD`; date-only precision is preserved (`date_precision`).
- Numbers: canonical decimal strings in SQLite, parsed with `Decimal`. Original value/unit kept (`value_original`, `unit_original`).
- Identifiers (`cik`, `series_id`, `class_id`) are strings; leading zeros kept. Ticker alone is not identity.

| Table | Grain / key | Notes |
| --- | --- | --- |
| sources | `source_id` | YAML registry with purpose, endpoint, owner, permissions, retention, coverage and frequency. Removed sources stay in the database for provenance with imports disabled. |
| source_import_runs | `run_id` + `source_id` | Inserted, skipped and rejected row counts per source in a local CSV batch. The matching ingestion run records the finish time. |
| funds | `fund_id` (one ETF product) | Optional `identity_source_id` and evidence reference for sourced imports. Launch date basis is actual, inception proxy, conversion, or unknown. Active from launch through the day before closure. Unknown launch dates are excluded from counts. |
| fund_identifiers | fund_id + type + value | cik, series_id, class_id |
| evidence | `evidence_id` per (source, external id, content hash) | revisions numbered; `published_at` != `first_observed_at` != `retrieved_at`; body NULL when retention is metadata_only |
| evidence_associations | evidence x source record | syndicated copies keep provenance without new evidence |
| events | `event_id` per (evidence, type) | `candidate_fund_ids` records the proposal's matches; an accepted review records the resolved `fund_id` and may supply `effective_date` |
| metric_observations | (source, external_record_id, revision) | `as_of_date` (measurement), `available_at` (source availability, may be empty), `first_observed_at` (set by importer), `effective_from/to` (fees) |
| review_actions | audit trail | reviewer, decision, previous/new values |
| reports | `report_id` includes profile, window, mode, cutoff, client and applied filters | draft, reviewed, or finalized with a saved snapshot |
| report_artifacts | `report_id` | Exact Markdown, HTML and manifest for each saved report |
| report_checkpoints | versioned report definition | Last successful end date, cutoff, and report ID |
| feed_cursors / feed_runs | source ID / collection attempt | Cached validators and collection outcomes |
| product_tags / tag_reviews | fund and tag / reviewed fund | Filter assignments and audit-preserving analyst overrides |

Metrics: `net_assets`, `total_assets`, `expense_ratio_net`, `expense_ratio_gross`, `management_fee` (fees as annual decimals);
`actual_revenue` uses explicit `period_start` and exclusive `period_end` dates. Revenue comparisons use
exact periods and consistently matched products. Reported net flows are stored separately.
Coverage states: available, unavailable_baseline, unavailable_current, stale, incompatible_scope, incompatible_currency,
incompatible_basis, unapproved, unavailable_common_date, outside_effective_interval, fee_asset_date_gap, not_active.
Empty = unknown (rejected on import for values); zero is a valid value; percent change from a zero baseline = N/A.
Taxonomy IDs, labels, dimensions and parent relationships are versioned through the client configuration.
