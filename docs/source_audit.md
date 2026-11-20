# Source audit

Milestone 1 reads local CSV files. On November 20, 2026, a bounded web check read one issuer product
page and one SEC reporting-period sample with a companion prospectus. Direct HTTPS to each host from
the workspace received a proxy CONNECT 403. The web reader returned the displayed documents. Application
network access and recurring collection are outside this check.

| Source | Role | Adapter in this repo | Permission evidence | Smoke test | Status |
| --- | --- | --- | --- | --- | --- |
| demo_metrics_import / demo_news_import / demo_syndicator | synthetic fixtures | CSV importers (tested) | authored in this repository | n/a | enabled in demo only |
| approved_news_import / approved_metrics_import | future real manual imports | CSV importers (tested with synthetic data) | none recorded | not run | disabled |
| SEC N-PORT bulk (S01/S02) and EDGAR filings | net assets and series identity | not built | SEC public filing reuse and fair access | one IVV filing checked | candidate |
| SEC fund tickers / submissions (S03/S04) | identifiers, filing discovery | not built | needs `SEC_USER_AGENT` | not run | blocked on build and User-Agent |
| SEC risk/return (S05/S06) | fees | not built | - | not run | deferred |
| Issuer RSS/press pages (N01-N05), product pages (P01-P03) | news / product facts | not built | brief lists restrictive or unknown terms | not run | disabled; permission required |
| iShares IVV product page | product identity, fund net assets, and fee display | none | recurring reuse unverified | HTML fields checked | read-only validation |
| ETFdb (S09) | discovery | none | commercial compilation restricted without permission | not run | do not use |

Activation checklist per source is in section 4.3 of the brief (feed URL, response/parse result, permission basis
and owner, retention, AI use, cadence, known gaps, timestamped smoke test).

## iShares IVV sample

The page identifies IVV on NYSE Arca (CUSIP `464287200`). Key Facts lists USD 833,393,580,703 in fund net
assets as of November 19, 2026. This is a full USD amount at product fund scope. Dividing by the 1,159,000,000
shares outstanding on that date gives a per-share value that rounds to the published NAV of USD 719.06.
[iShares Core S&P 500 ETF](https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf)

The Fees section displays a 0.03% management fee and a separately labeled 0.03% expense ratio. The management
fee converts to an annual decimal of 0.0003. The labels refer to the current prospectus. The page does not
specify net or gross for the generic expense ratio or give it the net assets' measurement date.
[iShares Fees](https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf#fees)

Public viewing was verified. A license for recurring collection or archival reuse of this iShares product page
could not be established. BlackRock's corporate-site terms separately limit automated monitoring or copying
of that site without permission. The product page is unsuitable for recurring pilot use without a recorded
permission basis and a supported access route. [BlackRock corporate-site terms](https://www.blackrock.com/corporate/compliance/terms-and-conditions)

## Alternate source in SEC EDGAR

The public filing index associates IVV with iShares Trust CIK `0001100663`, series `S000004310`, and class
`C000012040`. The filing was published August 25, 2026 for the report period ending June 30, 2026.
[Form N-PORT filing index](https://www.sec.gov/Archives/edgar/data/1100663/000207169126019760/0002071691-26-019760-index.htm)

Item B.1(c) reports USD 888,128,937,468.17 in net assets for the fund series and its consolidated
subsidiaries. Total assets of USD 889,637,196,076.52 less liabilities of USD 1,508,258,608.35 reconcile to
that amount. Keep the series scope on import until a reviewed crosswalk allows a product mapping.
[Form N-PORT items A.2, A.3 and B.1](https://www.sec.gov/Archives/edgar/data/1100663/000207169126019760/xslFormNPORT-P_X01/primary_doc.xml)

IVV's July 31, 2026 summary prospectus separately reports a management fee of 0.03% and total annual
fund operating expenses of 0.03%. Record the prospectus date and each definition independently. An explicit
net ratio requires review of the prospectus expense basis and any waivers or reimbursements.
[IVV summary prospectus](https://www.sec.gov/Archives/edgar/data/1100663/000119312526327930/d113852d497k.htm)

The SEC permits reuse of EDGAR public filing content and sets fair-access conditions for automated access.
Those conditions include a declared user agent with contact information and a ceiling of 10 requests per
second. EDGAR is a free candidate for a reviewed import path. This sample establishes one reporting-period
observation and one dated prospectus. Assess publication lag, amendments, identity mapping, and coverage
before treating it as an operational feed. No financial source is enabled in the supplied pilot config.
[SEC reuse guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions) · [SEC fair access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
