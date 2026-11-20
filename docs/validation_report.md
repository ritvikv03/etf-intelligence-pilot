# Offline ETF pilot validation

## Phase 3 source registry and real-data check

November 20, 2026. PR #1 had already merged at `cb213e1`. A fresh virtual environment installed the
supplied pinned requirements and an editable snapshot of that commit on Linux with Python 3.12.14.
The baseline passed `pip check`, all 44 tests, the populated CLI workflow and backup restoration.

| Check | Observed result |
| --- | --- |
| Suite after the registry changes | `pip check` passed and `python -m pytest -q` passed 48 tests. New cases cover registry validation, source-specific outcomes, purpose separation, identity attribution, and migration rollback. |
| Populated offline workflow | `init`, two `demo` runs, `doctor`, weekly and custom `report`, accept/reject/defer `review`, and `backup` with restore all passed. The repeated demo exported identical bytes for the same review state. The Alpha/Beta Decimal values matched again. |
| Populated upgrade | Applied `002_source_registry` to an isolated copy of the Phase 2 backup. SQLite integrity and foreign-key checks passed. Existing report snapshots, metrics, evidence, associations, events, and review actions matched the original rows. |
| Public-data import | Imported one reviewed IVV identity and one USD fund net-assets observation from the single-class EDGAR filing. Each rerun skipped one duplicate. Both sources reported success and one skipped row in `doctor`. |
| Observation trace | `obs_4c758c3e717f8c0e` stored USD 888,128,937,468.17 with June 30 measurement, August 25 availability and November 20 first observation. It appears in `rpt_649551f7b9c6` and its manifest. Markdown, HTML and JSON reproduced byte-for-byte at the same cutoff. |

The IVV report showed a current snapshot with an unavailable baseline, weighted fee, and change.
The import used a reviewed one-product mapping. The approval and ownership settings applied to the
isolated sample only. The shared pilot configuration remains disabled. See [source audit](source_audit.md#one-off-edgar-import).

The instrumented suite and CLI runs recorded no network calls with socket creation blocked.
Direct HTTPS through the workspace proxy failed with CONNECT 403 for iShares and the SEC. The
web reader displayed both official sources. iShares recurring-use permission remains unverified.
The SEC sample used its published public-filing reuse permission. The end-to-end check covers one
filing and one date. Automated collection, feed health, amendment ingestion across different
filings, and broader coverage were outside this check. See [next milestones](next_milestones.md).

## Phase 2 offline baseline

November 20, 2026. The offline analyst workflow passed on Linux x86_64 with Python 3.12.14. Real financial
coverage still depends on an approved source and reviewed product mappings.

## Checkout and setup

The follow-up began with a clean tracked checkout on `codex/etf-pilot-validation` at `70cd717`. That commit
already restored the `src/etf_pilot`, `configs`, `migrations`, `templates`, `imports`, and `tests` layout.
The original upload at `ef831c3` had header-only root product and news CSVs. The available history contained
no populated originals. The demo replacement records are synthetic and were authored to match the existing
metric fixtures and tests. The checkout runs directly using the editable install.

A fresh virtual environment installed the supplied pinned requirements and the editable project.
`pip check` reported no broken requirements. The installed pinned versions include pytest 9.1.1,
Pydantic 2.14.0, PyYAML 6.0.3, and Jinja2 3.1.6. Tests and CLI commands ran against a clean snapshot of the
staged files with isolated demo and pilot paths. Linux syscall tracing blocked socket creation and recorded
no network calls in the verified test and CLI run. See [setup commands](../README.md#setup).

| Test run | Result |
| --- | --- |
| Historical flat upload, via the external layout workaround | 34 passed, 2 failed |
| Follow-up baseline at `70cd717`, before code changes | 36 passed |
| Follow-up with regressions before the fixes | 34 passed, 9 failed |
| Final `python -m pytest -q` | 44 passed |

The regressions cover malformed row isolation, removing sources without losing archived evidence, permission
references, review validation and amended-event deduplication, report timezone and scope, configured fee
and currency labels, and use of common measurement dates for weighted fees and the proxy.

## CLI and data checks

| Commands exercised | Observed result |
| --- | --- |
| `init demo`, `demo` twice, `doctor demo` | First run imported 5 funds, 13 metric observations, and 4 evidence records. There were 5 source associations, 3 event proposals, and zero rejected rows. The syndication duplicate was associated with existing evidence. |
| Second `demo` | All fixture rows were skipped as duplicates. Data counts matched, and report `rpt_8179f85d1ebd` produced byte-identical Markdown, HTML, and manifest files. |
| `report demo weekly` and `report demo custom --start 2026-10-01 --end 2026-10-08` | Produced draft exports. The exclusive October 8 end made October 7 the current measurement date. The cutoff at October 7 20:00 UTC selected GAMA's USD 5 million observation. The October 8 12:00 UTC cutoff selected the USD 5.5 million amendment. Both revisions remained in SQLite. |
| `report demo last_run`, `report demo full_history` | Both returned exit code 2 with an implementation-gap message. |
| `review-list demo`, `review demo accept/reject/defer`, `report demo weekly`, `demo` again | Accepting the ambiguous ECHO event required a fund ID. An impossible effective date returned exit code 2. Accepting ECHO for `demo_echo_a`, rejecting the GAMA launch announcement, and deferring the ALFA fee announcement produced 3 audit actions. Report regeneration displayed the accepted and deferred events. Reimporting the demo preserved the review decisions. |
| `backup demo` and restore | A populated backup passed SQLite integrity and foreign-key checks, matched all tables including reviews, and regenerated byte-identical Markdown, HTML, and manifest for the reviewed weekly report. Its manifest references 11 observations, 2 news evidence records and 2 events. |
| `init pilot_client`, `doctor pilot_client`, `report pilot_client weekly` | Pilot data and exports used separate paths. Both supplied sources were disabled and all data tables were empty. The draft identified the issuer subset and explicitly marked financial and lifecycle coverage unavailable. |

Draft reports can be regenerated under the same ID when a review decision changes. Byte comparison of
the repeated demo used the same review state. The restore used the same review state, window, cutoff, and
client configuration as the reviewed report.

## Independent financial acceptance

The Alpha/Beta unit tests compare Decimal calculations to independent expected values. The populated demo
also reproduced the case through import, aggregation and export.

| Matched-cohort measure | Baseline | Current | Change |
| --- | --- | --- | --- |
| Fund net assets | USD 150,000,000 | USD 165,000,000 | +USD 15,000,000 (+10%) |
| Alpha net expense ratio | 0.25% | 0.20% | -5 basis points |
| Beta net expense ratio | 0.40% | 0.40% | 0 basis points |
| Asset-weighted net expense ratio | 0.30% | approximately 0.254545% | approximately -4.545 basis points |
| Annualized expense-based proxy | USD 450,000 | USD 420,000 | -USD 30,000 (approximately -6.666667%) |

The Markdown and HTML show rounded display figures. The proxy is an annualized run-rate from net assets
and net expense ratios. Actual revenue and net flows require distinct observations. Missing or incompatible
inputs remain unavailable. See [financial acceptance tests](../tests/test_metrics_arithmetic.py).

## Sources and remaining limitations

The iShares IVV product page was readable through the web reader. Its asset amount and NAV reconciled, and
permission for recurring reuse could not be established. SEC EDGAR public reuse guidance and one IVV N-PORT
filing provide a candidate for review. The filing's June 30, 2026 series-level net assets reconciled to its total
assets less liabilities. A separate July 31, 2026 prospectus verified the management fee and total operating
expenses definitions. Direct workspace HTTPS to both hosts received proxy CONNECT 403. See [source audit](source_audit.md).

The source check covered one fund and one N-PORT period. Historical depth, reliable recurring access,
product-level crosswalks at scale, and real imports remain unverified. The editable checkout on Linux was
tested. The checks did not cover standalone wheels, Windows, other Python versions, concurrent operations,
large datasets, or fault recovery across multiple sources. If earlier software overwrote an accepted
event's candidate IDs, the original ambiguity cannot be recovered from that event row.

Analyst acceptance, taxonomy, RSS archival, qualitative synthesis, finalization, and additional
lookbacks remain tracked in [next milestones](next_milestones.md).
