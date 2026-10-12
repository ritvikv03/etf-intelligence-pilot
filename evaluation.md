# Evaluation

**Automated tests:** 36 pytest tests pass on Python 3.12.3 (run 2026-10-08; fixtures are synthetic). They cover the section 19.1
arithmetic fixture (150M -> 165M, +10%, alpha -5 bp, weighted fee 0.30% -> ~0.2545%, proxy 450,000 -> 420,000, -30,000 / ~-6.67%),
rerun idempotency, amendments and cutoff selection, missing baseline, empty vs zero, fee unit normalization, gross/series/currency/
unapproved/stale exclusions, mixed as-of dates, future launches, launch+closure, ambiguous match review, syndication and correction
dedup, metadata-only retention, DST/month-end/leap windows, config validation, pilot isolation, HTML escaping, manifest contents.

**Not evaluated:** classification accuracy (no model; keyword rules only, no reviewed sample), real-data correctness, analyst time
saved, business usefulness, `last_run`/late-arrival checkpoint behavior across finalized reports, backup restoration, live sources.
No accuracy, confidence or time-saving figure is claimed. Business acceptance targets in the brief (section 19.3) are unmeasured.
