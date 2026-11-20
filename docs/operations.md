# Operations (Milestone 1)

- Run manually; no scheduler, service or collector exists yet. A sleeping laptop is not an always-on host.
- Imports are rerunnable. Rejected rows are staged in `rejected_rows` (file, row, field, suggestion) and printed.
- Corrections: new `revision` for metrics; edited article text becomes a new revision of the same evidence record.
- Review: `review-list`, then `review accept|reject|defer`. Ambiguous events need `--fund-id`.
- `python -m etf_pilot backup <client>` uses the SQLite backup API to write to `data/backups/<client>/`. Copy
  `configs/` with the backup. A populated demo restore regenerated identical reports from the same cutoff and configuration.
- Retention: metadata-only sources never store article bodies. Expiry jobs are not implemented.
- Do not expose anything publicly: there is no authentication.
- Changes to config, parser or template should be noted in `docs/decisions.md`.
