# Source audit

**No live endpoint was contacted in this build.** Milestone 1 contains no network code. The table records what
exists, not what works. "Smoke test" columns are intentionally empty; do not read the brief's research notes as test results.

| Source | Role | Adapter in this repo | Permission evidence | Smoke test | Status |
| --- | --- | --- | --- | --- | --- |
| demo_metrics_import / demo_news_import / demo_syndicator | synthetic fixtures | CSV importers (tested) | authored in this repository | n/a | enabled in demo only |
| approved_news_import / approved_metrics_import | future real manual imports | CSV importers (tested with synthetic data) | none recorded | not run | disabled |
| SEC N-PORT bulk (S01/S02) | net assets, series identity | not built (Milestone 2) | public filing data per brief | not run | blocked on build |
| SEC fund tickers / submissions (S03/S04) | identifiers, filing discovery | not built | needs `SEC_USER_AGENT` | not run | blocked on build and User-Agent |
| SEC risk/return (S05/S06) | fees | not built | - | not run | deferred |
| Issuer RSS/press pages (N01-N05), product pages (P01-P03) | news / product facts | not built | brief lists restrictive or unknown terms | not run | disabled; permission required |
| ETFdb (S09) | discovery | none | commercial compilation restricted without permission | not run | do not use |

Activation checklist per source is in section 4.3 of the brief (feed URL, response/parse result, permission basis
and owner, retention, AI use, cadence, known gaps, timestamped smoke test).
