# ETF intelligence pilot - Milestone 1 (offline vertical slice)

Local, no-network, no-API-key research workflow: import products / metrics / news from CSV, compute metrics
deterministically (Decimal), propose events by keyword rules, review them, and export an evidence-linked
**draft** briefing (Markdown, HTML, JSON manifest). Decision support only: nothing trades, distributes or publishes.

## Status

Implemented and tested: config validation, SQLite migrations, product/metric/news CSV importers, identity
ambiguity handling, net-assets / fee / weighted-fee / expense-proxy calculations, windows (all lookbacks except
`last_run` and `full_history`), keyword events, review queue with audit trail, template report, CLI, backup.
**Not yet built** (later milestones): Streamlit UI, RSS/Atom collection, SEC N-PORT importer and SEC identity
resolution, taxonomy/filters, optional Ollama classification, report checkpoints / `last_run`, finalization,
`as_known_then` mode. No live endpoint has been contacted. See `docs/`.

## Setup (tested: Python 3.12.3, Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"  # versions used are recorded in requirements-lock.txt
python -m etf_pilot init demo
python -m etf_pilot demo           # imports synthetic fixtures, writes the draft report
python -m pytest
```

Outputs: `exports/demo/<report_id>.{md,html,manifest.json}`; database `data/demo/demo.sqlite3`.
Re-running `demo` inserts nothing new and reproduces the same report ID and text.

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
A custom window end is exclusive: pass the day after the last day you want included.

## Real (pilot) data

`configs/pilot.yaml` has every source disabled. To use real data a named owner must record the permission basis
(ingestion, retention, AI use, redistribution) in the config, supply products with verified identifiers, and
import approved exports. An unknown permission is not permission; the config validator refuses to enable such a source.
Do not mix demo and pilot data: separate databases and export directories are enforced.

## Methodology (short)

Fund net assets only (`asset_basis=net`, product scope, USD). Gross/total assets, series/class scope, other
currencies, unapproved or stale observations are excluded and labeled. Matched-cohort change is the like-for-like
figure; full-universe snapshots change membership and are not growth. Fees are annual decimals; percent and
basis-point inputs must declare their unit. The expense-based figure is a snapshot proxy, never "revenue".
Asset change is not net flow. See `docs/data_dictionary.md`.
