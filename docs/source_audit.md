# Source audit

Milestone 1 reads local CSV exports. The public issuer sample below was checked through a web reader.

| Source | Role | Adapter in this repo | Permission evidence | Smoke test | Status |
| --- | --- | --- | --- | --- | --- |
| demo_metrics_import / demo_news_import / demo_syndicator | synthetic fixtures | CSV importers (tested) | authored in this repository | n/a | enabled in demo only |
| approved_news_import / approved_metrics_import | future real manual imports | CSV importers (tested with synthetic data) | none recorded | not run | disabled |
| SEC N-PORT bulk (S01/S02) | net assets, series identity | not built (Milestone 2) | public filing data per brief | not run | blocked on build |
| SEC fund tickers / submissions (S03/S04) | identifiers, filing discovery | not built | needs `SEC_USER_AGENT` | not run | blocked on build and User-Agent |
| SEC risk/return (S05/S06) | fees | not built | - | not run | deferred |
| Issuer RSS/press pages (N01-N05), product pages (P01-P03) | news / product facts | not built | brief lists restrictive or unknown terms | not run | disabled; permission required |
| iShares IVV product page | product identity and fund net assets | none | permission basis pending | HTML fields checked 2026-11-20 | read-only validation |
| ETFdb (S09) | discovery | none | commercial compilation restricted without permission | not run | do not use |

Activation checklist per source is in section 4.3 of the brief (feed URL, response/parse result, permission basis
and owner, retention, AI use, cadence, known gaps, timestamped smoke test).

## iShares IVV sample

The web reader returned HTML from the public product page on November 20, 2026. Direct workspace HTTPS received
a proxy 403. [iShares Core S&P 500 ETF](https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf)

- The page identifies IVV on NYSE Arca (CUSIP 464287200). Key Facts lists USD 833,393,580,703 in fund net
  assets as of November 19, 2026. The pilot field mapping is `net_assets`, `product` scope, `net` basis,
  `USD`, `currency_units`, and `as_of_date=2026-11-19`.
- Dividing those net assets by the 1,159,000,000 shares outstanding on the same date gives USD 719.0626 per
  share, which rounds to the published NAV of USD 719.06.
- The Fees section lists a 0.03% management fee, which converts to an annual decimal of 0.0003. Its
  expense ratio is also 0.03%. A fee observation needs a dated prospectus, and the expense-ratio field
  needs an explicit net or gross basis.
