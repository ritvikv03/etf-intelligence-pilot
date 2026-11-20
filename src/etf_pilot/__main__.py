"""CLI. Thin wrapper over etf_pilot.service / reports / review."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .config import ConfigError, load_config
from .db import backup, open_db, utc_now
from .importers import import_metrics, import_news, import_products
from .reports import generate_report
from .review import decide, list_pending
from .service import DEMO_CUTOFF, DEMO_END, check_observed_override, run_demo
from .windows import LOOKBACKS


def _print_import(res):
    print(res.summary())
    for e in res.errors:
        print(f"  REJECTED {e['file']} row {e['row']} field {e['field']}: {e['message']} -> {e['suggestion']}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="etf_pilot", description="ETF intelligence pilot (Milestone 1: offline vertical slice)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("init", "demo", "doctor", "backup", "review-list"):
        s = sub.add_parser(name)
        s.add_argument("client", nargs="?", default="demo")
    for name in ("import-products", "import-metrics", "import-news"):
        s = sub.add_parser(name)
        s.add_argument("client")
        s.add_argument("file", type=Path)
        s.add_argument("--observed-at", help="demo mode only")
    s = sub.add_parser("report")
    s.add_argument("client")
    s.add_argument("lookback", choices=LOOKBACKS)
    s.add_argument("--end", type=date.fromisoformat, help="exclusive local end date (default: today; demo: 2026-10-08)")
    s.add_argument("--start", type=date.fromisoformat, help="custom lookback only")
    s.add_argument("--cutoff", help="frozen data cutoff, ISO UTC (default: now; demo: fixed)")
    s = sub.add_parser("review")
    s.add_argument("client")
    s.add_argument("decision", choices=["accept", "reject", "defer"])
    s.add_argument("event_id")
    s.add_argument("--reviewer", required=True)
    s.add_argument("--reason", default="")
    s.add_argument("--fund-id")
    s.add_argument("--effective-date")
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
            print(f"report {rep['report_id']} (draft)\n  {rep['markdown']}\n  {rep['html']}\n  {rep['manifest']}")
        elif a.cmd in ("import-products", "import-metrics", "import-news"):
            conn = open_db(cfg)
            if a.cmd == "import-products":
                _print_import(import_products(conn, cfg, a.file))
            else:
                obs = check_observed_override(cfg, a.observed_at)
                fn = import_metrics if a.cmd == "import-metrics" else import_news
                _print_import(fn(conn, cfg, a.file, obs))
        elif a.cmd == "report":
            conn = open_db(cfg)
            end = a.end or (DEMO_END if cfg.mode == "demo" else date.today())
            cutoff = a.cutoff or (DEMO_CUTOFF if cfg.mode == "demo" else utc_now())
            rep = generate_report(conn, cfg, a.lookback, end, cutoff, profile=f"{a.lookback}", start_date=a.start)
            print(f"report {rep['report_id']} (draft)\n  {rep['markdown']}\n  {rep['html']}\n  {rep['manifest']}")
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
            print("  live endpoints tested: none (no network code in Milestone 1)")
            blocked = [s.source_id for s in cfg.sources if not s.enabled]
            print(f"  disabled sources: {', '.join(blocked) or 'none'}")
        elif a.cmd == "backup":
            print(backup(cfg, cfg.root / "data" / "backups" / cfg.client_id))
    except (ConfigError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
