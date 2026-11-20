"""SQLite access with file-based migrations and explicit transactions."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import ClientConfig, project_root


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    mdir = migrations_dir or project_root() / "migrations"
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for f in sorted(mdir.glob("*.sql")):
        if f.stem in done:
            continue
        conn.executescript("BEGIN;\n" + f.read_text() + "\nCOMMIT;")
        conn.execute("INSERT INTO schema_migrations VALUES (?,?)", (f.stem, utc_now()))
        conn.commit()
        applied.append(f.stem)
    return applied


def open_db(cfg: ClientConfig) -> sqlite3.Connection:
    conn = connect(cfg.db_file)
    migrate(conn)
    sync_sources(conn, cfg)
    return conn


def sync_sources(conn: sqlite3.Connection, cfg: ClientConfig) -> None:
    with conn:
        for s in cfg.sources:
            conn.execute(
                """INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET source_type=excluded.source_type, enabled=excluded.enabled,
                   permission_status=excluded.permission_status, permission_reference=excluded.permission_reference,
                   retention_mode=excluded.retention_mode, ai_allowed=excluded.ai_allowed,
                   internal_report_allowed=excluded.internal_report_allowed,
                   redistribution_allowed=excluded.redistribution_allowed, coverage_notes=excluded.coverage_notes""",
                (s.source_id, s.source_type, int(s.enabled), s.permission_status, s.permission_reference,
                 s.retention_mode, int(s.ai_allowed), int(s.internal_report_allowed),
                 int(s.redistribution_allowed), s.coverage_notes),
            )


def backup(cfg: ClientConfig, dest_dir: Path) -> Path:
    """Consistent SQLite backup (sqlite3 backup API) plus config copy."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = dest_dir / f"{cfg.client_id}-{stamp}.sqlite3"
    src = connect(cfg.db_file)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return target
