"""Shared service layer used by the CLI (and later the UI). One implementation of every calculation."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .config import ClientConfig, project_root
from .db import open_db, utc_now
from .importers import import_metrics, import_news, import_products
from .reports import generate_report

# Fixed demo clock so the synthetic scenario is reproducible (demo mode only).
DEMO_STAGES = [
    ("products.csv", "products", "2026-09-25T12:00:00Z"),
    ("metrics_baseline.csv", "metrics", "2026-09-30T18:00:00Z"),
    ("news.csv", "news", "2026-10-07T15:00:00Z"),
    ("metrics_current.csv", "metrics", "2026-10-07T18:00:00Z"),
    ("metrics_amendment.csv", "metrics", "2026-10-08T01:00:00Z"),
]
DEMO_CUTOFF = "2026-10-08T12:00:00Z"
DEMO_END = date(2026, 10, 8)


def check_observed_override(cfg: ClientConfig, observed_at: str | None) -> str:
    if observed_at and cfg.mode != "demo":
        raise ValueError("--observed-at is only allowed in demo mode; first_observed_at is set by the importer")
    return observed_at or utc_now()


def run_demo(cfg: ClientConfig, root: Path | None = None) -> dict:
    if cfg.mode != "demo":
        raise ValueError("the demo command only runs against a demo config")
    root = root or project_root()
    conn = open_db(cfg)
    results = []
    for fname, kind, observed in DEMO_STAGES:
        path = root / "imports" / "demo" / fname
        if kind == "products":
            results.append(import_products(conn, cfg, path))
        elif kind == "metrics":
            results.append(import_metrics(conn, cfg, path, observed))
        else:
            results.append(import_news(conn, cfg, path, observed))
    report = generate_report(conn, cfg, "weekly", DEMO_END, DEMO_CUTOFF, profile="demo_weekly")
    return {"imports": results, "report": report, "conn": conn}
