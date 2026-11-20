"""Save report bundles and maintain their draft, reviewed, and finalized states."""
from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from .db import utc_now

ARTIFACT_EXTENSIONS = {"markdown": "md", "html": "html", "manifest": "manifest.json"}


def report_paths(cfg, report_id: str) -> dict:
    return {kind: cfg.export_path / f"{report_id}.{ext}" for kind, ext in ARTIFACT_EXTENSIONS.items()}


def saved_context(conn, report_id: str) -> dict:
    row = conn.execute("SELECT status,snapshot_json FROM reports WHERE report_id=?", (report_id,)).fetchone()
    if row is None:
        raise ValueError("unknown report")
    return {**json.loads(row["snapshot_json"]), "status": row["status"]}


def read_artifacts(conn, report_id: str) -> dict:
    row = conn.execute("SELECT markdown,html,manifest FROM report_artifacts WHERE report_id=?", (report_id,)).fetchone()
    if row is None:
        raise ValueError("this report has no stored artifacts. Generate a new draft to use review and export.")
    return dict(row)


@contextmanager
def publish_artifacts(cfg, report_id: str, bundle: dict):
    """Restore the previous exports if publication or the associated DB commit fails."""
    paths = report_paths(cfg, report_id)
    cfg.export_path.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=cfg.export_path) as directory:
        stage = Path(directory)
        replaced = []
        for kind, path in paths.items():
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError("report export path must be a regular file")
            if path.exists():
                shutil.copyfile(path, stage / f"{kind}.previous")
            (stage / kind).write_text(bundle[kind], encoding="utf-8")
        try:
            for kind, path in paths.items():
                (stage / kind).replace(path)
                replaced.append(kind)
            yield
        except BaseException:
            for kind in reversed(replaced):
                previous = stage / f"{kind}.previous"
                if previous.exists():
                    previous.replace(paths[kind])
                else:
                    paths[kind].unlink(missing_ok=True)
            raise


def serialized_manifest(context: dict) -> str:
    return json.dumps(context["manifest"], indent=2, sort_keys=True)


def store_bundle(conn, report_id: str, bundle: dict) -> None:
    conn.execute(
        """INSERT INTO report_artifacts VALUES (?,?,?,?) ON CONFLICT(report_id) DO UPDATE
           SET markdown=excluded.markdown, html=excluded.html, manifest=excluded.manifest""",
        (report_id, bundle["markdown"], bundle["html"], bundle["manifest"]),
    )


def export_saved_report(conn, cfg, report_id: str) -> dict:
    """Recover exported files from the canonical SQLite copy."""
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        bundle = read_artifacts(conn, report_id)
        with publish_artifacts(cfg, report_id, bundle):
            conn.commit()
    return report_paths(cfg, report_id)


def change_report_status(conn, cfg, report_id: str, status: str, reviewer: str) -> dict:
    if status not in {"reviewed", "finalized"} or not reviewer.strip():
        raise ValueError("select reviewed or finalized and provide a reviewer name")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        context = saved_context(conn, report_id)
        previous = context["status"]
        expected = "draft" if status == "reviewed" else "reviewed"
        if previous != expected:
            raise ValueError(f"only a {expected} briefing can be marked {status}")
        bundle = read_artifacts(conn, report_id)
        markers = {
            "markdown": f"*Status: {previous.upper()}. Report ID `{report_id}`.*",
            "html": f"<em>Status: {previous.upper()}. Report ID <code>{report_id}</code>.</em>",
        }
        for kind, before_marker in markers.items():
            if before_marker not in bundle[kind]:
                raise ValueError("report export status needs regeneration before review")
            after_marker = before_marker.replace(f"Status: {previous.upper()}", f"Status: {status.upper()}", 1)
            bundle[kind] = bundle[kind].replace(before_marker, after_marker, 1)
        now = utc_now()
        context["status"] = context["manifest"]["status"] = status
        context["manifest"][status] = {"by": reviewer.strip(), "at": now}
        bundle["manifest"] = serialized_manifest(context)
        conn.execute("UPDATE reports SET status=?,snapshot_json=? WHERE report_id=?",
                     (status, json.dumps(context, default=str, sort_keys=True), report_id))
        store_bundle(conn, report_id, bundle)
        conn.execute(
            """INSERT INTO review_actions(entity_type,entity_id,reviewer,decision,previous_value,new_value,at)
               VALUES ('report',?,?,?,?,?,?)""",
            (report_id, reviewer.strip(), status, previous, status, now),
        )
        with publish_artifacts(cfg, report_id, bundle):
            conn.commit()
    return context
