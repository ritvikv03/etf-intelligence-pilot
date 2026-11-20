"""A loopback-only frontend for the same services used by the CLI."""
from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import closing
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from .artifacts import ARTIFACT_EXTENSIONS, change_report_status, read_artifacts, saved_context
from .db import open_db, source_health, utc_now
from .feeds import collect_feeds, feed_health
from .importers import import_metrics, import_news, import_products
from .reports import generate_report
from .review import decide, list_pending
from .service import DEMO_CUTOFF, DEMO_END, run_demo
from .taxonomy import product_tags, review_tags
from .windows import LOOKBACKS

ASSETS = Path(__file__).with_name("web_assets")
MAX_REQUEST = 2 * 1024 * 1024
CONTENT_TYPES = {
    "html": "text/html; charset=utf-8", "markdown": "text/markdown; charset=utf-8",
    "manifest": "application/json; charset=utf-8",
}


class ReportInput(BaseModel):
    lookback: str
    end: date
    start: date | None = None
    cutoff: str | None = None
    issuer_ids: list[str] = Field(default_factory=list, max_length=50)
    tag_ids: list[str] = Field(default_factory=list, max_length=50)
    pillar_ids: list[str] = Field(default_factory=list, max_length=20)
    request_model: bool = False


class EventInput(BaseModel):
    event_id: str
    reviewer: str
    decision: Literal["accept", "reject", "defer"]
    reason: str = ""
    fund_id: str | None = None
    effective_date: str | None = None


class TagInput(BaseModel):
    fund_id: str
    reviewer: str
    tag_ids: list[str] = Field(max_length=100)


class StatusInput(BaseModel):
    report_id: str
    reviewer: str
    status: Literal["reviewed", "finalized"]


class ImportInput(BaseModel):
    kind: Literal["products", "metrics", "news"]
    filename: str
    content: str
    source_id: str | None = None


def _default_end(cfg) -> date:
    return DEMO_END if cfg.mode == "demo" else datetime.now(ZoneInfo(cfg.report_timezone)).date()


def _default_cutoff(cfg) -> str:
    return DEMO_CUTOFF if cfg.mode == "demo" else utc_now()


def workspace_state(conn, cfg, report_id: str | None = None) -> dict:
    reports = [dict(r) for r in conn.execute(
        """SELECT r.report_id,r.status,r.window_start,r.window_end,r.data_cutoff,r.profile,
                  a.report_id IS NOT NULL AS exportable
           FROM reports r LEFT JOIN report_artifacts a ON a.report_id=r.report_id
           ORDER BY r.rowid DESC LIMIT 100"""
    )]
    tags = product_tags(conn)
    identifiers = {}
    for row in conn.execute("SELECT * FROM fund_identifiers ORDER BY id_type, value"):
        identifiers.setdefault(row["fund_id"], {}).setdefault(row["id_type"], []).append(row["value"])
    listing_changes = {}
    for row in conn.execute(
        """SELECT entity_id,previous_value,new_value,at FROM review_actions WHERE entity_type='fund'
           AND decision='import_update' ORDER BY id DESC"""
    ):
        before, after = json.loads(row["previous_value"]), json.loads(row["new_value"])
        if (before.get("ticker"), before.get("listing_venue")) != (after.get("ticker"), after.get("listing_venue")):
            entries = listing_changes.setdefault(row["entity_id"], [])
            if len(entries) < 5:
                entries.append({"ticker": before.get("ticker"), "venue": before.get("listing_venue"), "at": row["at"]})
    products = [
        {**dict(row), "tag_ids": sorted(tags.get(row["fund_id"], ())),
         "identifiers": identifiers.get(row["fund_id"], {}), "listing_history": listing_changes.get(row["fund_id"], [])}
        for row in conn.execute(
            """SELECT f.fund_id,f.ticker,f.name,f.issuer_id,f.listing_venue,f.review_status,t.reviewer
               FROM funds f LEFT JOIN tag_reviews t ON f.fund_id=t.fund_id ORDER BY f.ticker,f.fund_id"""
        )
    ]
    source_meta = {s.source_id: s for s in cfg.sources}
    feeds = feed_health(conn)
    sources = []
    for row in source_health(conn):
        item = dict(row)
        source = source_meta.get(row["source_id"])
        if source:
            item.update({
                "type": source.source_type, "endpoint": str(source.endpoint) if source.endpoint else None,
                "permission": source.permission_status, "retention": source.retention_mode,
                "coverage": source.coverage_notes, "frequency": source.update_frequency,
            })
        item["feed"] = feeds.get(row["source_id"])
        sources.append(item)
    return {
        "client": cfg.client_display_name, "mode": cfg.mode, "banner": cfg.demo_banner, "timezone": cfg.report_timezone,
        "default_end": _default_end(cfg).isoformat(), "model_enabled": cfg.ai.enabled,
        "lookbacks": LOOKBACKS, "issuers": cfg.universe.issuer_ids,
        "catalog": [t.model_dump() for t in cfg.taxonomy], "pillars": [p.model_dump() for p in cfg.pillars],
        "reports": reports, "report": saved_context(conn, report_id or reports[0]["report_id"]) if report_id or reports else None,
        "products": products, "sources": sources,
        "pending": [{**row, "choices": json.loads(row["candidate_fund_ids"])} for row in list_pending(conn)],
    }


def _upload(conn, cfg, data):
    uploaded = ImportInput.model_validate(data)
    filename = Path(uploaded.filename).name
    if not filename.lower().endswith(".csv"):
        raise ValueError("choose a CSV file")
    with TemporaryDirectory() as directory:
        path = Path(directory) / filename
        path.write_text(uploaded.content, encoding="utf-8")
        if uploaded.kind == "products":
            result = import_products(conn, cfg, path, source_id=uploaded.source_id)
        else:
            importer = import_metrics if uploaded.kind == "metrics" else import_news
            result = importer(conn, cfg, path, _default_cutoff(cfg))
    return {"message": result.summary(), "errors": result.errors[:20]}


def _mutate(conn, cfg, path, data):
    if path == "/api/report":
        req = ReportInput.model_validate(data)
        result = generate_report(conn, cfg, req.lookback, req.end, req.cutoff or _default_cutoff(cfg),
                                 profile="workspace", start_date=req.start, issuer_ids=req.issuer_ids,
                                 tag_ids=req.tag_ids, pillar_ids=req.pillar_ids, request_model=req.request_model)
        return {"message": "Briefing generated.", "report_id": result["report_id"]}
    if path == "/api/review":
        req = EventInput.model_validate(data)
        decide(conn, **req.model_dump())
        return {"message": "Event decision recorded."}
    if path == "/api/tags":
        req = TagInput.model_validate(data)
        review_tags(conn, cfg, **req.model_dump())
        return {"message": "Product tags reviewed."}
    if path == "/api/status":
        req = StatusInput.model_validate(data)
        change_report_status(conn, cfg, **req.model_dump())
        return {"message": f"Briefing {req.status}.", "report_id": req.report_id}
    if path == "/api/collect":
        rows = collect_feeds(conn, cfg, data.get("source_id"))
        if not rows:
            return {"message": "No approved RSS sources are enabled."}
        failures = sum(row["status"] == "failed" for row in rows)
        return {"message": f"Checked {len(rows)} feeds. {failures} failed.", "collection": rows}
    if path == "/api/import":
        return _upload(conn, cfg, data)
    raise ValueError("unknown workspace action")


def make_server(cfg, port: int = 8765) -> HTTPServer:
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, content: bytes, kind: str, *, export=False, filename=None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", (
                "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
                if export else "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
            ))
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(content)

        def _json(self, status, data):
            self._reply(status, json.dumps(data, default=str).encode(), CONTENT_TYPES["manifest"])

        def _local_host(self):
            port = self.server.server_port
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self):
            if not self._local_host():
                self._json(403, {"error": "Use the local workspace address."})
                return
            request = urlsplit(self.path)
            query = parse_qs(request.query)
            try:
                if request.path == "/":
                    page = (ASSETS / "index.html").read_text(encoding="utf-8").replace("TOKEN_PLACEHOLDER", token)
                    self._reply(200, page.encode(), CONTENT_TYPES["html"])
                elif request.path in {"/app.css", "/app.js"}:
                    filename = request.path[1:]
                    mime = "text/css" if filename.endswith(".css") else "text/javascript"
                    self._reply(200, (ASSETS / filename).read_bytes(), mime + "; charset=utf-8")
                elif request.path == "/api/state":
                    with closing(open_db(cfg)) as conn:
                        self._json(200, workspace_state(conn, cfg, query.get("report", [None])[0]))
                elif request.path == "/api/export":
                    report_id = query.get("report", [""])[0]
                    kind = query.get("kind", ["html"])[0]
                    if kind not in CONTENT_TYPES or not report_id.startswith("rpt_") or len(report_id) != 16:
                        raise ValueError("unknown report export")
                    with closing(open_db(cfg)) as conn:
                        content = read_artifacts(conn, report_id)[kind]
                    filename = f"{report_id}.{ARTIFACT_EXTENSIONS[kind]}" if "download" in query else None
                    self._reply(200, content.encode(), CONTENT_TYPES[kind], export=True, filename=filename)
                else:
                    self._json(404, {"error": "Page not found."})
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except (OSError, sqlite3.Error):
                self._json(500, {"error": "The workspace could not open the requested data or export."})

        def do_POST(self):
            origin = self.headers.get("Origin")
            if (not self._local_host() or not secrets.compare_digest(self.headers.get("X-Workspace-Token", ""), token)
                    or (origin and origin != "http://" + self.headers["Host"])):
                self._json(403, {"error": "Refresh the local workspace before submitting."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST or self.headers.get_content_type() != "application/json":
                    raise ValueError("Send a JSON request under 2 MiB.")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Send a JSON object.")
                with closing(open_db(cfg)) as conn:
                    result = _mutate(conn, cfg, urlsplit(self.path).path, data)
                self._json(200, result)
            except ValidationError as error:
                detail = error.errors(include_input=False)[0]
                self._json(400, {"error": detail["msg"]})
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except (OSError, sqlite3.Error):
                self._json(500, {"error": "The operation could not write its data or exports. Check the workspace paths."})

    return HTTPServer(("127.0.0.1", port), Handler)


def serve(cfg, port: int = 8765) -> None:
    with closing(open_db(cfg)) as conn:
        has_data = conn.execute("SELECT 1 FROM funds LIMIT 1").fetchone() is not None
    if cfg.mode == "demo" and not has_data:
        run_demo(cfg)["conn"].close()
    with make_server(cfg, port) as server:
        print(f"ETF Intelligence workspace at http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
