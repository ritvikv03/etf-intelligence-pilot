# Next milestones

1. **Approve one financial data path.** Name a source owner and review the SEC public filing candidate.
   Verify identity from registrant, series, class and exchange records. Define how an approved series maps
   to a listed product, how amendments supersede one another, and how dated fee definitions align with
   asset observations. Start with one issuer subset and disclose measurement lags and missing periods.
   Actual issuer revenue and net flow each need a distinct authoritative observation.
2. **Collect and archive approved RSS or Atom sources.** Add per-source configuration and status, retain
   permitted metadata or content, record publication and retrieval dates, and test retries and deduplication.
   Set request, payload, runtime and retention bounds. Exercise slow sources, temporary failures, parser
   failures and partial coverage before any recurring collection.
3. **Add hierarchical product tags and composite filters.** Model issuer, strategy, asset class, and geography
   with stable IDs and multiple tags where needed. Distinguish listing country from investment exposure.
   Check that intersections of filters preserve consistent product identity and report coverage.
4. **Expand the product and financial reports.** Verify distinct product counts, launches, closures, and
   changes in assets and fees against approved data. Distinguish lifecycle events from watchlist expansions.
   Show new and departed products, approval status, matched cohorts, observation dates and missing-data reasons.
5. **Add evidence-linked qualitative synthesis.** Make themes and competitive developments traceable to
   archived sources. Evaluate any optional AI against analyst-reviewed examples for factual accuracy, date
   and identity handling, and citation completeness. Preserve deterministic financial calculations.
6. **Add checkpoints and finalization.** Preserve daily, weekly, monthly, quarterly, semiannual, annual,
   3-year, 5-year, 10-year, and custom windows. Implement `last_run` from a stored checkpoint and
   `full_history` over available archive coverage. Add immutable final report versions and test regeneration,
   review timing, and amendments at earlier cutoffs before offering `as_known_then`.
7. **Add UI and scheduling after manual acceptance.** Verify analyst review and backup workflows first.
   Design scoped access, health checks, recovery and deployment ownership before adding a recurring job or
   making a UI available.
