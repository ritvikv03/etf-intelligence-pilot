# Decisions and assumptions

All items are **provisional** (the brief's defaults, not confirmed by a client) unless marked otherwise.
Owner and approval fields are blank until a business reviewer is named. Date recorded: 2026-10-08.

| # | Decision | Status | Affects |
| --- | --- | --- | --- |
| 1 | Users: internal product-strategy/research analyst; internal draft use only | provisional | acceptance, distribution |
| 2 | Product grain: one ETF product with a stable internal `fund_id`; SEC series/class are identifiers, not the grain | provisional | aggregation |
| 3 | Assets = product-level fund net assets in USD; `total_assets`/gross/series/class never enter totals | provisional | asset metrics |
| 4 | Revenue unavailable; optional "Annualized expense-based proxy" (net assets x net expense ratio), off in pilot config, on in demo | provisional | pricing pillar |
| 5 | Primary fee = net expense ratio; gross and management fee stored as separate metrics | provisional | fees |
| 6 | Four reporting pillars, configurable | provisional | report layout |
| 7 | Windows are [B, E) in America/Chicago converted to UTC; baseline = day before B, current = day before E | provisional | all comparisons |
| 8 | Staleness: assets 120 days, fees 400 days, fee/asset date gap 120 days; no forward-filling | provisional | coverage |
| 9 | Report mode `retrospective` only; `as_known_then` rejected by config validation until built | implementation limit | reproducibility claims |
| 10 | Group totals require a shared as-of date; otherwise "unavailable_common_date" | provisional | totals |
| 11 | All sources disabled in `pilot.yaml`; manual imports need a recorded permission basis | provisional | live activation |
| 12 | Hosted models forbidden; AI disabled; template report is the only generator | provisional | AI |
| 13 | Keyword event proposals are never authoritative; accepted only via review | implementation choice | events |
| 14 | Matching: ticker token first, then full fund name; any ambiguity (multiple candidates) is queued, never auto-resolved | implementation choice | identity |
| 15 | Extra exclusion states beyond the brief: `incompatible_basis`, `outside_effective_interval`, `fee_asset_date_gap` | implementation choice | coverage labels |
| 16 | Simplified layout: sources live inside client configs (no separate sources.yaml/taxonomy.yaml yet); one service module | implementation choice | structure |
| 17 | A re-import of a changed product row updates it and logs the previous values in `review_actions`; metric corrections require a higher revision | implementation choice | audit |
