# Next milestones

## Phase 3 coverage follow-up

The editable registry and one-off SEC IVV import are verified. An operational source needs a named owner
and a permitted, working access route. Verify publication lag, amendments, date precision, and registrant,
series, class and exchange mappings across several funds before expanding the sample. Scope fee
observations to the dated prospectus definitions. Actual product revenue and net flows each need a
separate authoritative source. See [source audit](source_audit.md).

## Phase 4 manual RSS collection and archive

Assess five curated sources for access, retention and coverage. Cap the initial enabled set at ten,
with at most two simultaneous requests and one SQLite writer. Bound timeouts, response size, retries
and per-run work. Preserve source identifiers, canonical URLs, publication dates, observation dates,
revisions, collection results, and content covered by each source's terms.

Exercise repeats, syndication, edits, malformed feeds and unavailable endpoints. A failed source keeps
its prior cursor and a successful source retains its results. The report should show incomplete coverage.
Removing a source should disable collection and preserve evidence referenced by prior reports.

## Phase 5 product master and taxonomy

Keep ticker and venue history and distinguish funds, listings, series and share classes. Add hierarchical
issuer, strategy, asset-class and investment geography classifications with multiple exposure and style
tags where useful. Record unknowns, taxonomy versions, evidence and analyst corrections. Verify composite
filters such as US exposure and small capitalization and count each product once across tags.

Keep ambiguous identities outside authoritative totals. Test that human corrections survive reimport and
that lifecycle counts distinguish launches, closures, changes in coverage, and unknown lifecycle dates.
Label inception-derived dates as proxies.

## Phase 6 analytics and report time

Verify product counts, lifecycle changes, fund net assets, fees, asset-weighted fees, and qualitative
developments against approved sources. Show evidence, scope, compatible measurement dates, matched
cohorts, and excluded or missing inputs. Keep gross and net expense ratios and management fees distinct.
Revenue figures require product-level revenue observations. The annualized expense-based proxy and
reported net flows have separate definitions.

Preserve daily, weekly, monthly, quarterly, semiannual, annual, 3-year, 5-year, 10-year and custom
windows. Add `last_run` checkpoints scoped to versioned report definitions and `full_history` windows
covering the available archive. Disclose gaps even in long windows. Use the configured timezone and
exclusive end boundary. Test missing baselines, true zeroes, stale or incompatible data, late arrivals,
and corrections. Verify failed exports preserve the last completed report and checkpoint.

## Phase 7 optional evaluated AI

Evaluate classification and evidence-linked synthesis for product activity, assets and growth, pricing
and economics, and themes and competition. Define acceptance thresholds on an analyst-labeled set
before selecting a model. Measure classification, relevance, citation accuracy, unsupported claims,
latency and cost. Compare local and hosted options only after reviewing hardware, data rights and cost.

Check numerical claims against deterministic results. Review uncertain identities and tags. Treat
retrieved article text as untrusted evidence. Record model, prompt, evidence and output versions.
Test a clearly labeled template fallback for model failures.

## Phase 8 analyst interface and finalization

Provide an internal view for managing sources, filters, windows, coverage, evidence and review decisions.
Keep draft, reviewed and finalized states distinct, including the approved content and exact inputs.
Verify final reports survive later imports and model changes and that all formats agree on numbers,
units, dates and evidence. Test safe rendering of external text. Distribution is manual.

## Phase 9 scheduling and recovery

Schedule after manual runs and recovery pass. Add a persistent runner with source health, bounded
retries and resource limits, run history, and failure messages. Test overlap prevention, one writer,
resuming interrupted tasks without duplicate or skipped evidence, populated restores and migration
rollback. Document restart from persisted state and account for terminated processes and connections.

## Phase 10 discovery and coverage

Use optional discovery to propose sources for analyst review. Measure marginal relevant coverage against
duplication, maintenance, processing cost and usage restrictions. Expand the issuer set, geographies,
data sources and available history incrementally. Keep fund-level revenue attribution and completeness
of historical data as explicit dependencies.

Demonstrate operational readiness with populated data, independent calculations, reruns, source failures,
revisions, coverage gaps, populated backup restoration and recovery. Report the coverage actually available.
