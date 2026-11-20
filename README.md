# ETF Intelligence

A local research workspace for reviewing ETF evidence and producing a weekly briefing. The browser and CLI
share the Python reporting services and SQLite database.

## Start the workspace

From the repository root with Python 3.11 or later.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -m pip check
python -m etf_pilot ui demo
```

Open `http://127.0.0.1:8765`. The demo loads synthetic records into a separate database on first start.
For an existing demo database, run `python -m etf_pilot demo` once to refresh the fixture tags.
The preview includes product counts, net assets, fees, coverage, and the evidence used in the briefing.
In **Filters**, select US investment exposure and Equity / Small capitalization to see the composite filter.
**Sources** shows permission and collection health and accepts local CSVs. Use **Analyst review** to resolve
events and edit tags, then **Report library** to mark a briefing reviewed, finalize it, and open the saved
HTML or download its manifest.

The application binds to loopback for a single local analyst. Team deployment requires authentication and
access controls. Choose `ui pilot_client` or pass a client YAML path for real inputs.

## Reports and evidence

- The source registry in the client YAML records purpose, ownership, permission, retention, frequency, and
  coverage. CSV imports and approved RSS/Atom feeds share the same archive and deduplication rules.
- Taxonomy IDs are editable in YAML. Child tags roll up to their parent. Multiple selected tags must all
  match. Product IDs and listing history distinguish funds with the same ticker.
- The briefing includes lifecycle counts and changes, product-level net assets, fees, and asset-weighted
  rates. Reported product revenue requires eligible observations for the exact reporting period. The
  annualized expense proxy and realized revenue have separate inputs and meanings.
- Available windows include daily, weekly, monthly, quarterly, semiannual, annual, 3-, 5-, and 10-year,
  custom dates, since last briefing, and full archive. Window ends are exclusive in the client timezone.
  Since last briefing uses the previous successful run for the same configuration and filters. Full archive
  begins at the oldest available observation or approved lifecycle record, and coverage gaps remain visible.
- The evidence summary works offline. Optional synthesis and tag suggestions can use an evaluated local
  Ollama model. Financial calculations use Decimal. Model suggestions require analyst review.
- Briefings progress from draft to reviewed to finalized. SQLite stores the exact exports and manifest, so
  later imports and model changes preserve reviewed copies.

## Command line

```bash
python -m etf_pilot demo
python -m etf_pilot report demo weekly --tag us_exposure --tag small_cap
python -m etf_pilot report demo last_run --end 2026-10-15 --tag us_exposure --tag small_cap
python -m etf_pilot report demo full_history
python -m etf_pilot doctor pilot_client
python -m etf_pilot collect pilot_client
python -m etf_pilot refresh pilot_client
python -m etf_pilot backup pilot_client
python -m pytest -q
```

Reports can also select `--issuer`, `--pillar`, `--start` for a custom or initial last-run window, and
`--cutoff` in UTC ISO format. The demo uses a fixed clock for reproducibility. `collect` checks the curated
feeds once. `refresh` collects and generates one draft, suitable for an existing local scheduler.
Use `python -m etf_pilot --help` for CSV imports, approvals, model evaluation, and export recovery.

## Production data and permissions

The shared pilot covers approved product records in a small US-listed ETF universe. The shipped config
has no enabled real sources. Use verified CSVs and approve owners and HTTPS feed endpoints in the client
configuration before use. A single SEC IVV observation verified the manual path in an isolated database.
Approved recurring datasets and live collection still require environment access and rights review.
[Source audit](docs/source_audit.md)

[Operations](docs/operations.md) · [Requirements and process](docs/requirements_and_process.md) ·
[Validation results](docs/validation_report.md) · [Remaining rollout checks](docs/next_milestones.md)
