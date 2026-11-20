# Local operations

## Sources and refresh

Keep the source registry in the client YAML. Each enabled RSS source needs an approved public HTTPS feed
endpoint, `purpose: news`, an owner, a permission reference, and internal-report permission. Review retention
and AI permission separately. Start with a small curated list. For CSVs, use the existing source IDs and
templates. If manual source terms permit only metadata, the archive omits article bodies.

Run `python -m etf_pilot collect pilot_client` or use **Check approved feeds** in the workspace. Requests
run sequentially, with at most ten configured active feeds, an 8-second socket timeout, a 1 MiB response
limit and a 200-entry cap. The collector accepts RSS and Atom and uses saved ETag or Last-Modified validators.
It checks public address resolution and disables redirects. A failed feed keeps its previous cursor.
Source states and import counts remain visible in `doctor` and the workspace. A later run reuses stable
evidence identities and preserves source revisions.

For an existing local job runner, use `python -m etf_pilot refresh pilot_client` to collect and generate a
single draft in the configured window. Per-client locks prevent overlapping collection and refresh runs.
The command returns a failure status for incomplete feed checks and retains successful sources and the
draft coverage notes. Configure recurring execution only after validating approved endpoints and access.

## CSV and report recovery

CSV templates are in `imports/templates/`. Rejected rows have a file, row number, field and suggestion.
Use a new `revision` for corrected metric observations. The same evidence identifier and changed content
retain a new immutable revision in the archive. Include `tag_ids` as pipe-separated IDs for product imports.
For actual revenue, include `period_start` and `period_end`, a full amount in `currency_units`, the currency,
and a source locator. Use an approved `actual_revenue` source and product scope for aggregation.

The report library can mark a draft reviewed and then finalize it. Each step records the analyst.
The canonical HTML, Markdown, and JSON manifest are stored together in SQLite. If exports are lost or an
external interruption leaves them out of sync, use `python -m etf_pilot export <client> <report_id>` to
recreate them. Older reports created before the artifact migration retain their existing snapshots and files.

Use `python -m etf_pilot backup <client>` and archive the client configuration with the backup. Restore a
copy under an isolated database path before swapping or regenerating any local outputs. Keep the database,
exports, CSVs, and evaluation corpora outside Git. The browser workspace is intended for loopback use.

## Evaluate optional local synthesis

Set `OLLAMA_MODEL` to an installed local model name. Use `evaluate-ai` with a researcher-labeled JSON corpus
of 5–50 permitted cases. The input includes `reviewed_by`, `permission_reference`, and `cases`. Each case
contains a `payload` with `pillars`, `funds` and `tags` maps, and `evidence` records containing IDs, titles,
and excerpts. Record expected product/tag pairs in `expected_tags`. Record approved text variants and their
citations in `approved_summaries`, with `pillar`, `text`, and `evidence_ids` on each item. The scorer matches
approved variants conservatively and omits the answers from model input.

```bash
python -m etf_pilot evaluate-ai pilot_client /path/to/labeled-corpus.json > /path/to/model-evaluation.json
```

Review the result before setting `ai.enabled: true` and `ai.evaluation_path` to that local file. The gate
requires at least 95% citation accuracy, 85% exact tag agreement, 80% relevance, zero unsupported claims,
and at most 25 seconds measured per case. An optional local model uses only evidence approved for AI use.
The evidence summary is shown when the model, evaluation, or response checks are unavailable.
