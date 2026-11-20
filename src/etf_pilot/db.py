"""SQLite access with file-based migrations and explicit transactions."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
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


@contextmanager
def run_lock(database: Path, purpose: str):
    """Use a separate SQLite lock so a long collection need not lock the data database."""
    database.parent.mkdir(parents=True, exist_ok=True)
    lock = sqlite3.connect(database.with_suffix(f".{purpose}.sqlite3"), timeout=0)
    try:
        try:
            lock.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            if error.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                raise
            raise ValueError(f"a {purpose} run is already in progress") from None
        yield
    finally:
        lock.close()


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    mdir = migrations_dir or project_root() / "migrations"
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for f in sorted(mdir.glob("*.sql")):
        if f.stem in done:
            continue
        with conn:
            conn.executescript("BEGIN;\n" + f.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations VALUES (?,?)", (f.stem, utc_now()))
        applied.append(f.stem)
    return applied


def open_db(cfg: ClientConfig) -> sqlite3.Connection:
    conn = connect(cfg.db_file)
    migrate(conn)
    sync_sources(conn, cfg)
    return conn


def sync_sources(conn: sqlite3.Connection, cfg: ClientConfig) -> None:
    with conn:
        # Imports use the active registry. Keep removed rows for archived provenance.
        conn.execute("UPDATE sources SET enabled=0 WHERE enabled=1")
        for s in cfg.sources:
            conn.execute(
                """INSERT INTO sources(source_id,source_type,enabled,permission_status,permission_reference,
                                       retention_mode,ai_allowed,internal_report_allowed,redistribution_allowed,
                                       coverage_notes,purpose,endpoint,owner,update_frequency)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET source_type=excluded.source_type, enabled=excluded.enabled,
                   permission_status=excluded.permission_status, permission_reference=excluded.permission_reference,
                   retention_mode=excluded.retention_mode, ai_allowed=excluded.ai_allowed,
                   internal_report_allowed=excluded.internal_report_allowed,
                   redistribution_allowed=excluded.redistribution_allowed, coverage_notes=excluded.coverage_notes,
                   purpose=excluded.purpose, endpoint=excluded.endpoint, owner=excluded.owner,
                   update_frequency=excluded.update_frequency""",
                (s.source_id, s.source_type, int(s.enabled), s.permission_status, s.permission_reference,
                 s.retention_mode, int(s.ai_allowed), int(s.internal_report_allowed),
                 int(s.redistribution_allowed), s.coverage_notes, s.purpose, str(s.endpoint) if s.endpoint else None,
                 s.owner, s.update_frequency),
            )


def source_health(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Latest attributable CSV import result for each registered source."""
    return conn.execute(
        """SELECT s.source_id, s.enabled, s.purpose, s.owner,
                  ir.finished_at, sr.inserted, sr.skipped, sr.rejected,
                  CASE WHEN sr.run_id IS NULL THEN 'unrecorded'
                       WHEN sr.rejected = 0 THEN 'success'
                       WHEN sr.inserted + sr.skipped = 0 THEN 'failed'
                       ELSE 'partial' END AS status
           FROM sources s
           LEFT JOIN source_import_runs sr ON sr.source_id = s.source_id AND sr.run_id = (
               SELECT max(latest.run_id) FROM source_import_runs latest WHERE latest.source_id = s.source_id
           )
           LEFT JOIN ingestion_runs ir ON ir.run_id = sr.run_id
           ORDER BY s.source_id"""
    ).fetchall()


def backup(cfg: ClientConfig, dest_dir: Path) -> Path:
    """Create a consistent SQLite database backup."""
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
