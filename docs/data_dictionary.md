# Data dictionary

- Timestamps: UTC ISO 8601 (`...Z`). Dates: `YYYY-MM-DD`; date-only precision is preserved (`date_precision`).
- Numbers: canonical decimal strings in SQLite, parsed with `Decimal`. Original value/unit kept (`value_original`, `unit_original`).
- Identifiers (`cik`, `series_id`, `class_id`) are strings; leading zeros kept. Ticker alone is not identity.

| Table | Grain / key | Notes |
| --- | --- | --- |
| funds | `fund_id` (one ETF product) | `launch_date_basis`: actual / inception_proxy / conversion / unknown; active from launch_date through day before closure_date; unknown launch date = excluded from counts |
| fund_identifiers | fund_id + type + value | cik, series_id, class_id |
| evidence | `evidence_id` per (source, external id, content hash) | revisions numbered; `published_at` != `first_observed_at` != `retrieved_at`; body NULL when retention is metadata_only |
| evidence_associations | evidence x source record | syndicated copies keep provenance without new evidence |
| events | `event_id` per (evidence, type) | proposals; `needs_review` when 0 or >1 candidate funds; `effective_date` only from review, never from the publication date |
| metric_observations | (source, external_record_id, revision) | `as_of_date` (measurement), `available_at` (source availability, may be empty), `first_observed_at` (set by importer), `effective_from/to` (fees) |
| review_actions | audit trail | reviewer, decision, previous/new values |
| reports | `report_id` = hash(profile, window, mode, cutoff, client) | status `draft`; snapshot JSON stored |

Metrics: `net_assets`, `total_assets`, `expense_ratio_net`, `expense_ratio_gross`, `management_fee` (fees as annual decimals);
`actual_revenue`, `reported_net_flows` can be imported but are not used in any calculation.
Coverage states: available, unavailable_baseline, unavailable_current, stale, incompatible_scope, incompatible_currency,
incompatible_basis, unapproved, unavailable_common_date, outside_effective_interval, fee_asset_date_gap, not_active.
Empty = unknown (rejected on import for values); zero is a valid value; percent change from a zero baseline = N/A.
Taxonomy tables are not implemented yet.
