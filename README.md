# ETF intelligence pilot - Milestone 1 (offline vertical slice)

Internal research analysts use the pilot to prepare a weekly draft briefing. It imports local CSV data,
calculates financial figures with Decimal, queues keyword-based event proposals for review, and exports
evidence-linked Markdown and HTML reports with a JSON manifest.

## Status

Implemented and tested: config validation, SQLite migrations, product/metric/news CSV importers, identity
ambiguity handling, net-assets / fee / weighted-fee / expense-proxy calculations, windows (all lookbacks except
`last_run` and `full_history`), keyword events, review queue with audit trail, template report, CLI, backup.
**Not yet built** (later milestones): Streamlit UI, RSS/Atom collection, SEC N-PORT importer and SEC identity
resolution, taxonomy/filters, optional Ollama classification, report checkpoints / `last_run`, finalization,
`as_known_then` mode. See [validation results](docs/validation_report.md), [requirements and process](docs/requirements_and_process.md),
and [next milestones](docs/next_milestones.md).

## Setup

Run from the repository root. The editable checkout uses the adjacent configs, migrations, templates,
and CSV fixtures. Setup was verified on Linux with Python 3.12.14 and the system IANA time zone database.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -m pip check
python -m etf_pilot init demo
python -m etf_pilot demo           # imports synthetic fixtures, writes the draft report
python -m pytest -q
```

Outputs: `exports/demo/<report_id>.{md,html,manifest.json}`; database `data/demo/demo.sqlite3`.
Re-running `demo` with the same reviews skips previously imported rows and reproduces the report ID
and all three output files. Package installation can use the network. The CLI runtime needs local files.

## Manual weekly pilot briefing

```bash
python -m etf_pilot init pilot_client
python -m etf_pilot doctor pilot_client
python -m etf_pilot report pilot_client weekly
```

The tracked subset is US-listed ETFs from BlackRock, WisdomTree, and Global X with approved product records.
The supplied pilot config has no approved financial or news sources enabled, so its draft shows the
coverage gap. With approved inputs, import the products first, then the metrics and news. Review the queue
and report coverage before sharing an internal draft.

## Commands

```bash
python -m etf_pilot import-products  <client> <file.csv>
python -m etf_pilot import-metrics   <client> <file.csv>
python -m etf_pilot import-news      <client> <file.csv>
python -m etf_pilot report <client> weekly [--end YYYY-MM-DD] [--cutoff ISO_UTC]
python -m etf_pilot report <client> custom --start YYYY-MM-DD --end YYYY-MM-DD
python -m etf_pilot review-list <client>
python -m etf_pilot review <client> accept|reject|defer <event_id> --reviewer NAME [--fund-id ID] [--effective-date YYYY-MM-DD]
python -m etf_pilot doctor <client>
python -m etf_pilot backup <client>
```

`<client>` is a `client_id` from `configs/*.yaml` (`demo`, `pilot_client`). CSV templates: `imports/templates/`.
`--observed-at` exists only in demo mode (fixture clock); real imports stamp `first_observed_at` themselves.
Window ends are exclusive. Pass the day after the last day you want included. The pilot defaults to the
current date in its configured timezone. Format an explicit cutoff as `YYYY-MM-DDTHH:MM:SSZ`.

## Real (pilot) data

Edit the source list in `configs/pilot.yaml`. A named owner records the permission basis for ingestion,
retention, internal reporting, AI use, and redistribution. Enable an approved manual source using a
`permission_reference` and supply products with verified identifiers. Removing a source from YAML stops
new imports from it and keeps the archived source record. Keep local input files outside the checkout
and use distinct pilot and demo database and export paths. See [source audit](docs/source_audit.md).

## Methodology (short)

Fund net assets only (`asset_basis=net`, product scope, USD). Gross/total assets, series/class scope, other
currencies, unapproved or stale observations are excluded and labeled. Matched-cohort change is the like-for-like
figure; full-universe snapshots change membership and are not growth. Fees are annual decimals; percent and
basis-point inputs must declare their unit. The expense-based figure is a snapshot proxy, never "revenue".
Asset change is not net flow. See `docs/data_dictionary.md`.
