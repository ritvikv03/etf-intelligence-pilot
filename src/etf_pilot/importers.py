"""Row-validated CSV importers for products, metrics and news. Rerunnable and idempotent."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import ClientConfig
from .db import utc_now

PRODUCT_COLS = ("fund_id name ticker listing_venue listing_country product_type issuer_id currency cik series_id "
                "class_id inception_date launch_date launch_date_basis closure_date identity_evidence_id "
                "review_status").split()
METRIC_COLS = ("external_record_id fund_id metric_name value unit currency scope asset_basis as_of_date "
               "effective_from effective_to available_at available_at_precision source_id evidence_url "
               "evidence_locator revision review_status").split()
NEWS_COLS = ("external_record_id source_id title url published_at date_precision body_or_excerpt "
             "permission_reference retention_mode ai_allowed").split()

METRIC_NAMES = {"net_assets", "total_assets", "expense_ratio_net", "expense_ratio_gross", "management_fee",
                "actual_revenue", "reported_net_flows"}
FEE_METRICS = {"expense_ratio_net", "expense_ratio_gross", "management_fee"}
FEE_UNITS = {"annual_decimal", "percent", "basis_points"}
SCOPES = {"product", "class", "series", "issuer"}
BASES = {"net", "gross", "unknown"}
REVIEW = {"approved", "pending", "rejected"}
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "mc_cid", "mc_eid"}


@dataclass
class ImportResult:
    kind: str
    file: str
    inserted: int = 0
    skipped: int = 0
    rejected: int = 0
    errors: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        return f"{self.kind} {self.file}: inserted={self.inserted} skipped(duplicate)={self.skipped} rejected={self.rejected}"


class _Rows:
    """Reads a CSV with every cell as a string (identifiers keep leading zeros)."""

    def __init__(self, path: Path, required: list[str], res: ImportResult):
        self.path, self.res = path, res
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rd = csv.DictReader(fh)
            self.header = rd.fieldnames or []
            self.rows = list(rd)
        missing = [c for c in required if c not in self.header]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}; see imports/templates/")

    def err(self, rownum: int, fieldname: str | None, msg: str, fix: str):
        self.res.errors.append({"file": self.path.name, "row": rownum, "field": fieldname, "message": msg, "suggestion": fix})
        self.res.rejected += 1


def _iso_date(v: str) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    date.fromisoformat(v)  # raises ValueError
    return v


def _decimal(v: str) -> Decimal:
    d = Decimal(v.strip())
    if not d.is_finite():
        raise InvalidOperation
    return d


def _canonical(value: Decimal) -> str:
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def canonical_url(url: str) -> str | None:
    if not url:
        return None
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(q), ""))


def _log_run(conn, kind, file, res: ImportResult, started: str):
    with conn:
        cur = conn.execute(
            "INSERT INTO ingestion_runs(kind,file,started_at,finished_at,status,inserted,skipped,rejected) VALUES (?,?,?,?,?,?,?,?)",
            (kind, file, started, utc_now(), "success" if not res.rejected else "partial", res.inserted, res.skipped, res.rejected))
        for e in res.errors:
            conn.execute("INSERT INTO rejected_rows(run_id,file,row_number,field,message,suggestion) VALUES (?,?,?,?,?,?)",
                         (cur.lastrowid, e["file"], e["row"], e["field"], e["message"], e["suggestion"]))


def import_products(conn: sqlite3.Connection, cfg: ClientConfig, path: Path) -> ImportResult:
    res = ImportResult("products", path.name)
    started = utc_now()
    rows = _Rows(path, PRODUCT_COLS, res)
    for i, r in enumerate(rows.rows, start=2):
        try:
            for c in ("fund_id", "name", "ticker", "listing_country", "product_type", "issuer_id", "currency"):
                if not r[c].strip():
                    raise _Bad(c, f"{c} is required", f"fill {c}; empty identifiers are never guessed")
            basis = r["launch_date_basis"].strip() or "unknown"
            if basis not in {"actual", "inception_proxy", "conversion", "unknown"}:
                raise _Bad("launch_date_basis", f"invalid value '{basis}'", "use actual, inception_proxy, conversion or unknown")
            if r["review_status"].strip() not in REVIEW:
                raise _Bad("review_status", f"invalid value '{r['review_status']}'", "use approved, pending or rejected")
            dates = {}
            for c in ("inception_date", "launch_date", "closure_date"):
                try:
                    dates[c] = _iso_date(r[c])
                except ValueError:
                    raise _Bad(c, f"'{r[c]}' is not YYYY-MM-DD", "use ISO dates") from None
            if dates["launch_date"] and basis == "unknown":
                raise _Bad("launch_date_basis", "launch_date given but basis is unknown", "state actual, inception_proxy or conversion")
        except _Bad as b:
            rows.err(i, b.field, b.msg, b.fix)
            continue
        new = (r["fund_id"].strip(), r["name"].strip(), r["ticker"].strip().upper(), r["listing_venue"].strip() or None,
               r["listing_country"].strip(), r["product_type"].strip(), r["issuer_id"].strip(), r["currency"].strip(),
               dates["inception_date"], dates["launch_date"], basis, dates["closure_date"],
               r["identity_evidence_id"].strip() or None, r["review_status"].strip())
        with conn:
            conn.execute("INSERT OR IGNORE INTO issuers VALUES (?,?)", (new[6], new[6].replace("_", " ").title()))
            old = conn.execute("SELECT * FROM funds WHERE fund_id=?", (new[0],)).fetchone()
            cols = ("fund_id name ticker listing_venue listing_country product_type issuer_id currency inception_date "
                    "launch_date launch_date_basis closure_date identity_evidence_id review_status").split()
            if old is None:
                conn.execute(f"INSERT INTO funds({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", new)
                res.inserted += 1
            elif tuple(old[c] for c in cols) == new:
                res.skipped += 1
            else:
                prev = {c: old[c] for c in cols}
                conn.execute("UPDATE funds SET " + ",".join(f"{c}=?" for c in cols[1:]) + " WHERE fund_id=?", new[1:] + (new[0],))
                conn.execute("INSERT INTO review_actions(entity_type,entity_id,reviewer,decision,reason,previous_value,new_value,at) "
                             "VALUES ('fund',?,?,?,?,?,?,?)", (new[0], "import", "import_update", f"re-import of {path.name}",
                                                              json.dumps(prev), json.dumps(dict(zip(cols, new))), utc_now()))
                res.inserted += 1
            for id_type in ("cik", "series_id", "class_id"):
                v = r[id_type].strip()
                if v:  # stored as strings so leading zeros survive
                    conn.execute("INSERT OR IGNORE INTO fund_identifiers VALUES (?,?,?)", (new[0], id_type, v))
    _log_run(conn, "products", path.name, res, started)
    return res


class _Bad(Exception):
    def __init__(self, field_, msg, fix):
        self.field, self.msg, self.fix = field_, msg, fix


def import_metrics(conn: sqlite3.Connection, cfg: ClientConfig, path: Path, observed_at: str) -> ImportResult:
    res = ImportResult("metrics", path.name)
    started = utc_now()
    rows = _Rows(path, METRIC_COLS, res)
    enabled = {r[0] for r in conn.execute("SELECT source_id FROM sources WHERE enabled=1 AND internal_report_allowed=1")}
    funds = {r[0] for r in conn.execute("SELECT fund_id FROM funds")}
    for i, r in enumerate(rows.rows, start=2):
        try:
            sid = r["source_id"].strip()
            if sid not in enabled:
                raise _Bad("source_id", f"source '{sid}' is unknown, disabled, or not approved for internal reports",
                           "record the permission basis and enable the source in the config")
            if r["fund_id"].strip() not in funds:
                raise _Bad("fund_id", f"unknown fund '{r['fund_id']}'", "import the product first")
            name = r["metric_name"].strip()
            if name not in METRIC_NAMES:
                raise _Bad("metric_name", f"unsupported metric '{name}'", f"use one of {sorted(METRIC_NAMES)}")
            if not r["value"].strip():
                raise _Bad("value", "empty value means unknown", "omit the row; empty is never converted to zero")
            try:
                raw = _decimal(r["value"])
            except InvalidOperation:
                raise _Bad("value", f"'{r['value']}' is not a number", "remove thousands separators and symbols") from None
            unit = r["unit"].strip()
            if name in FEE_METRICS:
                if unit not in FEE_UNITS:
                    raise _Bad("unit", f"fee unit '{unit}' not accepted", "state annual_decimal, percent or basis_points; magnitude is never guessed")
                value = {"annual_decimal": raw, "percent": raw / 100, "basis_points": raw / 10000}[unit]
                norm_unit = "annual_decimal"
            else:
                if unit not in {"currency_units", "usd"} and name in {"net_assets", "total_assets"}:
                    raise _Bad("unit", f"asset unit '{unit}' not accepted", "supply full currency units (unit=currency_units)")
                value, norm_unit = raw, unit
            scope, basis = r["scope"].strip(), r["asset_basis"].strip()
            if scope not in SCOPES:
                raise _Bad("scope", f"invalid scope '{scope}'", "use product, class, series or issuer")
            if basis not in BASES:
                raise _Bad("asset_basis", f"invalid asset_basis '{basis}'", "use net, gross or unknown")
            if r["review_status"].strip() not in REVIEW:
                raise _Bad("review_status", "invalid review_status", "use approved, pending or rejected")
            try:
                as_of = _iso_date(r["as_of_date"])
                eff_from, eff_to = _iso_date(r["effective_from"]), _iso_date(r["effective_to"])
                avail = _iso_date(r["available_at"])
                revision = int(r["revision"].strip() or "1")
            except ValueError:
                raise _Bad("as_of_date/effective/available_at/revision", "bad date or revision", "use YYYY-MM-DD and integer revision") from None
            if not as_of:
                raise _Bad("as_of_date", "as_of_date is required", "supply the measurement date")
            if not r["external_record_id"].strip():
                raise _Bad("external_record_id", "required for idempotent re-import", "supply a stable id")
        except _Bad as b:
            rows.err(i, b.field, b.msg, b.fix)
            continue
        obs_id = "obs_" + hashlib.sha256(f"{sid}|{r['external_record_id'].strip()}|{revision}".encode()).hexdigest()[:16]
        record = (r["fund_id"].strip(), name, _canonical(value), norm_unit, r["currency"].strip() or None, scope, basis,
                  as_of, eff_from, eff_to, avail, r["available_at_precision"].strip() or None)
        existing = conn.execute("SELECT * FROM metric_observations WHERE obs_id=?", (obs_id,)).fetchone()
        if existing:
            same = (existing["fund_id"], existing["metric_name"], existing["value"], existing["unit"], existing["currency"],
                    existing["scope"], existing["asset_basis"], existing["as_of_date"], existing["effective_from"],
                    existing["effective_to"], existing["available_at"], existing["available_at_precision"]) == record
            if same:
                res.skipped += 1
            else:
                rows.err(i, "revision", f"revision {revision} of {r['external_record_id']} already stored with different values",
                         "corrections must use a new, higher revision number")
            continue
        with conn:
            conn.execute("INSERT INTO metric_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (obs_id, r["external_record_id"].strip(), sid, record[0], name, record[2], norm_unit, record[4], scope,
                          basis, as_of, eff_from, eff_to, avail, record[11], observed_at,
                          r["evidence_url"].strip() or None, r["evidence_locator"].strip() or None, revision,
                          r["review_status"].strip(), format(raw, "f"), unit))
        res.inserted += 1
    _log_run(conn, "metrics", path.name, res, started)
    return res


def import_news(conn: sqlite3.Connection, cfg: ClientConfig, path: Path, observed_at: str) -> ImportResult:
    from .events import detect_events  # local import avoids a cycle

    res = ImportResult("news", path.name)
    started = utc_now()
    rows = _Rows(path, NEWS_COLS, res)
    enabled = {r[0]: r for r in conn.execute("SELECT * FROM sources WHERE enabled=1 AND internal_report_allowed=1")}
    for i, r in enumerate(rows.rows, start=2):
        try:
            sid = r["source_id"].strip()
            if sid not in enabled:
                raise _Bad("source_id", f"source '{sid}' is unknown, disabled, or not approved for internal reports",
                           "record the permission basis and enable the source in the config")
            if not r["title"].strip() or not r["external_record_id"].strip():
                raise _Bad("title/external_record_id", "required", "supply both")
            published, precision = r["published_at"].strip() or None, r["date_precision"].strip() or "unknown"
            if published:
                try:
                    date.fromisoformat(published[:10])
                except ValueError:
                    raise _Bad("published_at", f"'{published}' is not ISO", "use YYYY-MM-DD or ISO 8601") from None
            elif precision != "unknown":
                raise _Bad("date_precision", "date_precision must be 'unknown' when published_at is empty", "set unknown")
            if r["retention_mode"].strip() not in {"full", "metadata_only"}:
                raise _Bad("retention_mode", "invalid", "use full or metadata_only")
        except _Bad as b:
            rows.err(i, b.field, b.msg, b.fix)
            continue
        src = enabled[sid]
        retention = "metadata_only" if "metadata_only" in (src["retention_mode"], r["retention_mode"].strip()) else "full"
        body = r["body_or_excerpt"] if retention == "full" else None  # disallowed body is never retained
        ai_allowed = int(bool(src["ai_allowed"]) and r["ai_allowed"].strip().lower() in {"1", "true", "yes"})
        chash = hashlib.sha256("\n".join([r["title"].strip(), r["body_or_excerpt"].strip()]).encode()).hexdigest()
        canon = canonical_url(r["url"])
        ext = r["external_record_id"].strip()
        dup = conn.execute("SELECT evidence_id FROM evidence WHERE source_id=? AND external_record_id=? AND content_hash=?", (sid, ext, chash)).fetchone()
        if not dup and canon:
            dup = conn.execute("SELECT evidence_id FROM evidence WHERE canonical_url=? AND content_hash=?", (canon, chash)).fetchone()
        if dup:
            with conn:  # keep provenance for syndicated copies; no new evidence or events
                conn.execute("INSERT OR IGNORE INTO evidence_associations VALUES (?,?,?,?)", (dup[0], sid, ext, observed_at))
            res.skipped += 1
            continue
        rev = 1 + conn.execute("SELECT COUNT(*) FROM evidence WHERE source_id=? AND external_record_id=?", (sid, ext)).fetchone()[0]
        eid = "ev_" + hashlib.sha256(f"{sid}|{ext}|{chash}".encode()).hexdigest()[:16]
        with conn:
            conn.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (eid, sid, ext, rev, r["url"].strip() or None, canon, r["title"].strip(), published, precision,
                          observed_at, observed_at, body, chash, r["permission_reference"].strip() or src["permission_reference"],
                          retention, ai_allowed))
            conn.execute("INSERT OR IGNORE INTO evidence_associations VALUES (?,?,?,?)", (eid, sid, ext, observed_at))
            detect_events(conn, eid, r["title"].strip(), r["body_or_excerpt"], observed_at)
        res.inserted += 1
    _log_run(conn, "news", path.name, res, started)
    return res
