"""CLI. Thin wrapper over etf_pilot.service / reports / review."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ConfigError, load_config
from .artifacts import change_report_status, export_saved_report
from .db import backup, open_db, run_lock, source_health, utc_now
from .feeds import collect_feeds, feed_health
from .importers import import_metrics, import_news, import_products
from .reports import generate_report
from .review import decide, list_pending
from .service import DEMO_CUTOFF, DEMO_END, check_observed_override, run_demo
from .taxonomy import review_tags
from .windows import LOOKBACKS


def _print_import(res):
    print(res.summary())
    for e in res.errors:
        print(f"  REJECTED {e['file']} row {e['row']} field {e['field']}: {e['message']} -> {e['suggestion']}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="etf_pilot", description="ETF intelligence research workspace")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("init", "demo", "doctor", "backup", "review-list"):
        s = sub.add_parser(name)
        s.add_argument("client", nargs="?", default="demo")
    for name in ("import-products", "import-metrics", "import-news"):
        s = sub.add_parser(name)
        s.add_argument("client")
        s.add_argument("file", type=Path)
        s.add_argument("--observed-at", help="demo mode only")
        if name == "import-products":
            s.add_argument("--source-id", help="enabled product identity source for this file")
    s = sub.add_parser("report")
    s.add_argument("client")
    s.add_argument("lookback", choices=LOOKBACKS)
    s.add_argument("--end", type=date.fromisoformat, help="exclusive local end date (default: today; demo: 2026-10-08)")
    s.add_argument("--start", type=date.fromisoformat, help="custom window or an initial last-run window")
    s.add_argument("--cutoff", help="frozen data cutoff, ISO UTC (default: now; demo: fixed)")
    s.add_argument("--tag", action="append", default=[], help="taxonomic filter, repeat to require all selected tags")
    s.add_argument("--issuer", action="append", default=[], help="tracked issuer to include, repeat to select more")
    s.add_argument("--pillar", action="append", default=[], help="report pillar to include")
    s.add_argument("--local-ai", action="store_true", help="request evaluated local synthesis")
    s = sub.add_parser("review")
    s.add_argument("client")
    s.add_argument("decision", choices=["accept", "reject", "defer"])
    s.add_argument("event_id")
    s.add_argument("--reviewer", required=True)
    s.add_argument("--reason", default="")
    s.add_argument("--fund-id")
    s.add_argument("--effective-date")
    s = sub.add_parser("review-tags")
    s.add_argument("client")
    s.add_argument("fund_id")
    s.add_argument("--tag", action="append", default=[])
    s.add_argument("--reviewer", required=True)
    s = sub.add_parser("report-status")
    s.add_argument("client")
    s.add_argument("report_id")
    s.add_argument("status", choices=["reviewed", "finalized"])
    s.add_argument("--reviewer", required=True)
    s = sub.add_parser("collect")
    s.add_argument("client")
    s.add_argument("--source-id")
    s = sub.add_parser("refresh", help="run one explicit or externally scheduled collection and draft")
    s.add_argument("client")
    s = sub.add_parser("ui", help="open the local analyst workspace")
    s.add_argument("client", nargs="?", default="demo")
    s.add_argument("--port", type=int, default=8765)
    s = sub.add_parser("evaluate-ai", help="score an optional local model on researcher-labeled JSON")
    s.add_argument("client")
    s.add_argument("dataset", type=Path)
    s = sub.add_parser("export", help="restore the files for a saved briefing")
    s.add_argument("client")
    s.add_argument("report_id")
    a = p.parse_args(argv)

    try:
        cfg = load_config(a.client)
        if a.cmd == "init":
            conn = open_db(cfg)
            print(f"initialized {cfg.db_file} ({cfg.mode} mode)")
        elif a.cmd == "demo":
            out = run_demo(cfg)
            print(cfg.demo_banner)
            for r in out["imports"]:
                _print_import(r)
            rep = out["report"]
            print(f"report {rep['report_id']} ({rep['context']['status']})\n  {rep['markdown']}\n  {rep['html']}\n  {rep['manifest']}")
        elif a.cmd in ("import-products", "import-metrics", "import-news"):
            conn = open_db(cfg)
            if a.cmd == "import-products":
                _print_import(import_products(conn, cfg, a.file, source_id=a.source_id))
            else:
                obs = check_observed_override(cfg, a.observed_at)
                fn = import_metrics if a.cmd == "import-metrics" else import_news
                _print_import(fn(conn, cfg, a.file, obs))
        elif a.cmd == "report":
            conn = open_db(cfg)
            end = a.end or (DEMO_END if cfg.mode == "demo" else datetime.now(ZoneInfo(cfg.report_timezone)).date())
            cutoff = a.cutoff or (DEMO_CUTOFF if cfg.mode == "demo" else utc_now())
            rep = generate_report(conn, cfg, a.lookback, end, cutoff, profile=a.lookback, start_date=a.start,
                                  issuer_ids=a.issuer, tag_ids=a.tag, pillar_ids=a.pillar, request_model=a.local_ai)
            print(f"report {rep['report_id']} ({rep['context']['status']})\n  {rep['markdown']}\n  {rep['html']}\n  {rep['manifest']}")
        elif a.cmd in ("review-list",):
            conn = open_db(cfg)
            for r in list_pending(conn):
                print(f"{r['event_id']}  {r['review_status']:<12} {r['event_type']:<22} candidates={r['candidate_fund_ids']}  {r['title']}")
        elif a.cmd == "review":
            conn = open_db(cfg)
            decide(conn, a.event_id, a.decision, a.reviewer, a.reason, a.fund_id, a.effective_date)
            print(f"{a.decision}: {a.event_id}")
        elif a.cmd == "doctor":
            conn = open_db(cfg)
            print(f"config ok: {cfg.client_id} ({cfg.mode}); database {cfg.db_file}")
            for t in ("funds", "evidence", "events", "metric_observations", "reports"):
                print(f"  {t}: {conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
            print("  input mode: local CSV files")
            print("  source import health")
            for s in source_health(conn):
                state = "enabled" if s["enabled"] else "disabled"
                purpose = s["purpose"] or "unspecified purpose"
                owner = s["owner"] or "unassigned"
                last_result = s["status"]
                if s["finished_at"]:
                    last_result += (f" at {s['finished_at']} (inserted={s['inserted']}, "
                                    f"skipped={s['skipped']}, rejected={s['rejected']})")
                print(f"    {s['source_id']} ({purpose}, {state}, owner={owner}): {last_result}")
            for sid, last in feed_health(conn).items():
                print(f"    {sid} RSS status {last['status']} at {last['checked_at']}")
        elif a.cmd == "collect":
            rows = collect_feeds(open_db(cfg), cfg, a.source_id)
            if not rows:
                print("No approved RSS sources are enabled.")
            for row in rows:
                print(f"{row['source_id']}: {row['status']} ({row['detail'] or str(row['inserted']) + ' new'})")
            if any(row["status"] == "failed" for row in rows):
                return 1
        elif a.cmd == "refresh":
            with run_lock(cfg.db_file, "refresh"):
                conn = open_db(cfg)
                rows = collect_feeds(conn, cfg)
                end = DEMO_END if cfg.mode == "demo" else datetime.now(ZoneInfo(cfg.report_timezone)).date()
                cutoff = DEMO_CUTOFF if cfg.mode == "demo" else utc_now()
                report = generate_report(conn, cfg, cfg.report_schedule, end, cutoff, profile="scheduled")
                print(f"report {report['report_id']} at {report['html']}")
                if any(row["status"] == "failed" for row in rows):
                    return 1
        elif a.cmd == "review-tags":
            review_tags(open_db(cfg), cfg, a.fund_id, a.tag, a.reviewer)
            print(f"reviewed tags for {a.fund_id}")
        elif a.cmd == "report-status":
            change_report_status(open_db(cfg), cfg, a.report_id, a.status, a.reviewer)
            print(f"{a.report_id}: {a.status}")
        elif a.cmd == "export":
            for path in export_saved_report(open_db(cfg), cfg, a.report_id).values():
                print(path)
        elif a.cmd == "evaluate-ai":
            from .synthesis import evaluate_local_model

            with a.dataset.open("rb") as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("evaluation dataset exceeds 2 MiB")
            try:
                print(json.dumps(evaluate_local_model(cfg, json.loads(raw)), indent=2))
            except (KeyError, AttributeError, TypeError):
                raise ValueError("invalid labeled evaluation dataset format") from None
        elif a.cmd == "ui":
            from .web import serve

            serve(cfg, a.port)
        elif a.cmd == "backup":
            print(backup(cfg, cfg.root / "data" / "backups" / cfg.client_id))
    except (ConfigError, ValueError, OSError, sqlite3.Error, NotImplementedError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
