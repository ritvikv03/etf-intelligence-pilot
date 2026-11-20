# Evaluation

This page records the earlier branch verification at commit `70cd717`. See the
[current validation report](validation_report.md) for the follow-up implementation and CLI acceptance results.

## November 20, 2026 validation

A fresh Python 3.12.14 virtual environment on Linux x86_64 installed the listed requirements and the checkout in
editable mode. `pip check` passed. The baseline in the reconstructed runtime reproduced 34 passes and two failures
(`test_full_demo_is_reproducible_and_idempotent` and `test_manifest_lists_ids_and_versions`). The flattened checkout
had only blank product and news templates. The repaired layout keeps those templates in `imports/templates/` and
adds synthetic demo fixtures that match the existing metric records and exercise ambiguous tickers, late news,
syndication, and article revisions.

`python -m pytest -q` passed all 36 tests from the repaired checkout. The suite covers the section 19.1
arithmetic fixture (150M -> 165M, +10%, alpha -5 bp, weighted fee 0.30% -> ~0.2545%, proxy 450,000 -> 420,000, -30,000 / ~-6.67%),
rerun idempotency, amendments and cutoff selection, missing baseline, empty vs zero, fee unit normalization, gross/series/currency/
unapproved/stale exclusions, mixed as-of dates, future launches, launch+closure, ambiguous match review, syndication and correction
dedup, metadata-only retention, DST/month-end/leap windows, config validation, pilot isolation, HTML escaping, manifest contents.

The CLI commands `init demo`, `demo` (twice), `doctor demo`, `review-list demo`, and `backup demo` completed.
The first demo produced 5 funds, 13 metric observations, 4 news evidence records, and 3 event proposals with
zero rejected rows. The second run skipped all fixture rows and reproduced report `rpt_8179f85d1ebd` and
byte-identical Markdown, HTML, and manifest files. The matched cohort moved from USD 150 million to USD 165 million
(+10%) and its asset-weighted net expense ratio moved from 0.3000% to 0.2545%. The manifest references
11 observations, 3 news evidence records, and 3 events.

The populated SQLite backup passed integrity and foreign-key checks after restoration. It matched the original
tables and regenerated identical report files. Network syscall tracing with socket creation blocked recorded no
network calls during the suite or the demo CLI commands. The public issuer check is recorded in
[Source audit](source_audit.md).

Classification accuracy, analyst time saved, business usefulness, real-data ingestion, and `last_run` checkpoint
behavior across finalized reports remain unevaluated. Business acceptance targets in the brief (section 19.3)
are unmeasured.
