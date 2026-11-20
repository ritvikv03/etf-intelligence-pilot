"""Collect approved RSS and Atom feeds into the existing news archive."""
from __future__ import annotations

import csv
import ipaddress
import re
import socket
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from .config import ClientConfig, SourceConfig
from .db import run_lock, utc_now
from .importers import NEWS_COLS, canonical_url, import_news

MAX_BYTES = 1024 * 1024
MAX_ITEMS = 200
REQUEST_TIMEOUT = 8
USER_AGENT = "ETF-Intelligence-Pilot/1.0 (manual research RSS collector)"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_feed(url: str, validators: dict[str, str]):
    endpoint = urlsplit(url)
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username is not None:
        raise ValueError("use an approved HTTPS feed endpoint")
    addresses = socket.getaddrinfo(endpoint.hostname, endpoint.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError("feed endpoints must resolve to a public address")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", **validators})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=REQUEST_TIMEOUT) as response:
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("feed returned an unsupported content encoding")
            deadline = monotonic() + REQUEST_TIMEOUT
            body = bytearray()
            while monotonic() <= deadline:
                chunk = response.read1(min(64 * 1024, MAX_BYTES + 1 - len(body)))
                if not chunk:
                    return bytes(body), response.headers
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError("feed exceeds the 1 MiB limit")
            raise ValueError("feed body exceeded the response time budget")
    except HTTPError as exc:
        with exc:
            if exc.code == 304:
                return None, exc.headers
            raise ValueError(f"feed returned HTTP {exc.code}") from None
    except (URLError, OSError):
        raise ValueError("could not reach the feed within the request limits") from None


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(text: str, limit: int) -> str:
    parser = _PlainText()
    parser.feed(text[:limit * 2])
    parser.close()
    return " ".join(" ".join(parser.parts).split())[:limit]


def _name(element):
    return element.tag.rsplit("}", 1)[-1].lower()


def _read(element, *names):
    for name in names:
        for child in element:
            if _name(child) == name:
                return "".join(child.itertext()).strip()
    return ""


def _publication(value: str) -> tuple[str, str]:
    if not value:
        return "", "unknown"
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat(), "date"
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            instant = parsedate_to_datetime(value)
    except (ValueError, OverflowError):
        raise ValueError("feed contains an invalid publication date") from None
    if instant.tzinfo is None:
        return instant.date().isoformat(), "date"
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "timestamp"


def parse_feed(blob: bytes, endpoint: str, source: SourceConfig) -> list[dict]:
    if len(blob) > MAX_BYTES or b"\0" in blob or re.search(br"<!\s*(?:doctype|entity)\b", blob, re.I):
        raise ValueError("feed exceeds parser limits or contains unsupported XML declarations")
    try:
        root = ElementTree.fromstring(blob)
    except ElementTree.ParseError:
        raise ValueError("feed is malformed XML") from None
    if _name(root) == "rss":
        channel = next((element for element in root if _name(element) == "channel"), None)
        if channel is None:
            raise ValueError("RSS channel is missing")
        entries = [element for element in channel if _name(element) == "item"]
    elif _name(root) == "feed":
        entries = [element for element in root if _name(element) == "entry"]
    else:
        raise ValueError("expected RSS or Atom")
    if len(entries) > MAX_ITEMS:
        raise ValueError(f"feed exceeds the {MAX_ITEMS}-item limit")
    rows = []
    for entry in entries:
        link = next(
            (child.get("href") or (child.text or "").strip() for child in entry
             if _name(child) == "link" and child.get("rel", "alternate") == "alternate"), ""
        )
        link = urljoin(endpoint, link) if link else ""
        parts = urlsplit(link)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None:
            link = ""
        identity = _read(entry, "guid", "id") or canonical_url(link)
        title = _plain(_read(entry, "title"), 300)
        if not identity or len(identity) > 1024 or not title:
            raise ValueError("feed entry needs a title and a stable identifier or link")
        published, precision = _publication(_read(entry, "pubdate", "published", "date"))
        rows.append({
            "external_record_id": identity, "source_id": source.source_id, "title": title, "url": link,
            "published_at": published, "date_precision": precision,
            "body_or_excerpt": _plain(_read(entry, "description", "summary", "content", "encoded"), 4000),
            "permission_reference": source.permission_reference, "retention_mode": source.retention_mode,
            "ai_allowed": str(source.ai_allowed),
        })
    return rows


def _collect_one(conn, cfg, source, fetch):
    endpoint = str(source.endpoint)
    sid = source.source_id
    cursor = conn.execute(
        "SELECT etag, last_modified FROM feed_cursors WHERE source_id=? AND endpoint=?", (sid, endpoint)
    ).fetchone()
    validators = {}
    if cursor:
        if cursor["etag"]:
            validators["If-None-Match"] = cursor["etag"]
        if cursor["last_modified"]:
            validators["If-Modified-Since"] = cursor["last_modified"]
    body, headers = fetch(endpoint, validators)
    if body is None:
        if not validators:
            raise ValueError("feed returned unchanged without a saved cursor")
        return "unchanged", 0, 0
    rows = parse_feed(body, endpoint, source)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "feed.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=NEWS_COLS)
            writer.writeheader()
            writer.writerows(rows)
        result = import_news(conn, cfg, path, utc_now())
    if result.rejected:
        raise ValueError(f"{result.rejected} archived feed rows were rejected")
    conn.execute(
        """INSERT INTO feed_cursors VALUES (?,?,?,?)
           ON CONFLICT(source_id) DO UPDATE SET endpoint=excluded.endpoint, etag=excluded.etag,
                                               last_modified=excluded.last_modified""",
        (sid, endpoint, headers.get("ETag"), headers.get("Last-Modified")),
    )
    return "success", result.inserted, result.skipped


def collect_feeds(conn, cfg: ClientConfig, source_id: str | None = None, *, fetch=fetch_feed) -> list[dict]:
    """Use one request at a time and advance each cursor only on successful ingest."""
    sources = [
        s for s in cfg.sources if s.enabled and s.source_type == "rss" and (source_id is None or s.source_id == source_id)
    ]
    if source_id is not None and not sources:
        raise ValueError(f"no enabled RSS source named {source_id}")
    if not sources:
        return []
    with run_lock(cfg.db_file, "collection"):
        return _collect_sources(conn, cfg, sources, fetch)


def _collect_sources(conn, cfg, sources, fetch):
    results = []
    for source in sources:
        detail = None
        try:
            status, inserted, skipped = _collect_one(conn, cfg, source, fetch)
        except (ValueError, OSError) as exc:
            conn.rollback()
            detail = str(exc)[:250]
            status, inserted, skipped = "failed", 0, 0
        with conn:
            conn.execute(
                "INSERT INTO feed_runs(source_id,checked_at,status,inserted,skipped,detail) VALUES (?,?,?,?,?,?)",
                (source.source_id, utc_now(), status, inserted, skipped, detail),
            )
        results.append({
            "source_id": source.source_id, "status": status, "inserted": inserted, "skipped": skipped, "detail": detail,
        })
    return results


def feed_health(conn, cutoff: str | None = None) -> dict:
    return {
        row["source_id"]: dict(row) for row in conn.execute(
            """SELECT r.source_id, r.status, r.checked_at, r.inserted, r.skipped, r.detail FROM feed_runs r
               WHERE r.run_id IN (
                   SELECT max(run_id) FROM feed_runs WHERE (? IS NULL OR checked_at <= ?) GROUP BY source_id
               )""",
            (cutoff, cutoff),
        )
    }
