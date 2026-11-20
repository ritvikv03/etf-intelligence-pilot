"""Row-validated CSV importers for products, metrics and news. Rerunnable and idempotent."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import ClientConfig
from .db import utc_now
from .taxonomy import replace_tags, validated_tags

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
    source_counts: dict[str, Counter[str]] = field(default_factory=dict)

    def record(self, outcome: Literal["inserted", "skipped", "rejected"], source_id: str | None) -> None:
        if outcome == "inserted":
            self.inserted += 1
        elif outcome == "skipped":
            self.skipped += 1
        else:
            self.rejected += 1
        if source_id is not None:
            self.source_counts.setdefault(source_id, Counter())[outcome] += 1

    def summary(self) -> str:
        return f"{self.kind} {self.file}: inserted={self.inserted} skipped(duplicate)={self.skipped} rejected={self.rejected}"


class _Rows:
    """Reads a CSV with every cell as a string (identifiers keep leading zeros)."""

    def __init__(self, path: Path, required: list[str], res: ImportResult, source_id: str | None = None):
        self.path, self.res = path, res
        self.required = required
        self.source_id = source_id

    def __iter__(self):
        with self.path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            missing = [column for column in self.required if column not in header]
            if missing:
                raise ValueError(f"{self.path.name}: missing columns {missing}, see imports/templates/")
            for row_number, row in enumerate(reader, start=2):
                if None in row or None in row.values():
                    self.err(row_number, None, "row does not match the header's column count",
                             "use the CSV template and quote values containing commas", self.source_id)
                    continue
                yield row_number, row

    def err(self, rownum: int, fieldname: str | None, msg: str, fix: str, source_id: str | None = None):
        self.res.errors.append({"file": self.path.name, "row": rownum, "field": fieldname, "message": msg, "suggestion": fix})
        self.res.record("rejected", source_id)


def _iso_date(v: str) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    return date.fromisoformat(v).isoformat()


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
    status = "success"
    if res.rejected:
        status = "partial" if res.inserted or res.skipped else "failed"
    with conn:
        cur = conn.execute(
            "INSERT INTO ingestion_runs(kind,file,started_at,finished_at,status,inserted,skipped,rejected) VALUES (?,?,?,?,?,?,?,?)",
            (kind, file, started, utc_now(), status, res.inserted, res.skipped, res.rejected))
        conn.executemany(
            "INSERT INTO source_import_runs(run_id,source_id,inserted,skipped,rejected) VALUES (?,?,?,?,?)",
            [(cur.lastrowid, sid, counts["inserted"], counts["skipped"], counts["rejected"])
             for sid, counts in res.source_counts.items()],
        )
        for e in res.errors:
            conn.execute("INSERT INTO rejected_rows(run_id,file,row_number,field,message,suggestion) VALUES (?,?,?,?,?,?)",
                         (cur.lastrowid, e["file"], e["row"], e["field"], e["message"], e["suggestion"]))


def import_products(conn: sqlite3.Connection, cfg: ClientConfig, path: Path, *, source_id: str | None = None) -> ImportResult:
    res = ImportResult("products", path.name)
    started = utc_now()
    if source_id is not None:
        source = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
        try:
            _check_source(source, source_id, "product_identity")
        except _Bad as error:
            raise ValueError(error.msg) from None
    rows = _Rows(path, PRODUCT_COLS, res, source_id)
    cols = ("fund_id name ticker listing_venue listing_country product_type issuer_id currency inception_date "
            "launch_date launch_date_basis closure_date identity_evidence_id review_status identity_source_id").split()
    for i, r in rows:
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
            if source_id is not None and not r["identity_evidence_id"].strip():
                raise _Bad("identity_evidence_id", "sourced identity requires an evidence reference",
                           "supply the filing link or evidence identifier")
            tags = None
            if "tag_ids" in r:
                try:
                    tags = validated_tags(cfg, (tag.strip() for tag in r["tag_ids"].split("|") if tag.strip()))
                except ValueError as exc:
                    raise _Bad("tag_ids", str(exc), "use taxonomy IDs separated by |") from None
        except _Bad as b:
            rows.err(i, b.field, b.msg, b.fix, source_id)
            continue
        new = (r["fund_id"].strip(), r["name"].strip(), r["ticker"].strip().upper(), r["listing_venue"].strip() or None,
               r["listing_country"].strip(), r["product_type"].strip(), r["issuer_id"].strip(), r["currency"].strip(),
               dates["inception_date"], dates["launch_date"], basis, dates["closure_date"],
               r["identity_evidence_id"].strip() or None, r["review_status"].strip())
        with conn:
            conn.execute("INSERT OR IGNORE INTO issuers VALUES (?,?)", (new[6], new[6].replace("_", " ").title()))
            old = conn.execute("SELECT * FROM funds WHERE fund_id=?", (new[0],)).fetchone()
            identity_source = source_id
            if source_id is None and old is not None and tuple(old[c] for c in cols[:-1]) == new:
                identity_source = old["identity_source_id"]
            new += (identity_source,)
            previous_tags = None
            if tags is not None and not conn.execute("SELECT 1 FROM tag_reviews WHERE fund_id=?", (new[0],)).fetchone():
                previous_tags = tuple(
                    row[0] for row in conn.execute("SELECT tag_id FROM product_tags WHERE fund_id=? ORDER BY tag_id", (new[0],))
                )
            tags_changed = previous_tags is not None and previous_tags != tags
            if old is None:
                conn.execute(f"INSERT INTO funds({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", new)
                res.record("inserted", source_id)
            elif tuple(old[c] for c in cols) == new and not tags_changed:
                res.record("skipped", source_id)
            else:
                prev = {c: old[c] for c in cols}
                current = dict(zip(cols, new))
                if tags_changed:
                    prev["tag_ids"] = previous_tags
                    current["tag_ids"] = tags
                conn.execute("UPDATE funds SET " + ",".join(f"{c}=?" for c in cols[1:]) + " WHERE fund_id=?", new[1:] + (new[0],))
                conn.execute("INSERT INTO review_actions(entity_type,entity_id,reviewer,decision,reason,previous_value,new_value,at) "
                             "VALUES ('fund',?,?,?,?,?,?,?)", (new[0], "import", "import_update", f"re-import of {path.name}",
                                                              json.dumps(prev), json.dumps(current), utc_now()))
                res.record("inserted", source_id)
            for id_type in ("cik", "series_id", "class_id"):
                v = r[id_type].strip()
                if v:  # stored as strings so leading zeros survive
                    conn.execute("INSERT OR IGNORE INTO fund_identifiers VALUES (?,?,?)", (new[0], id_type, v))
            if tags_changed:
                replace_tags(conn, new[0], tags)
    _log_run(conn, "products", path.name, res, started)
    return res


class _Bad(Exception):
    def __init__(self, field_, msg, fix):
        self.field, self.msg, self.fix = field_, msg, fix


def _check_source(source: sqlite3.Row | None, source_id: str, purpose: str) -> None:
    if source is None or not source["enabled"] or not source["internal_report_allowed"]:
        raise _Bad("source_id", f"source '{source_id}' is unknown, disabled, or not approved for internal reports",
                   "record the permission basis and enable the source in the config")
    if source["purpose"] not in (None, purpose):
        raise _Bad("source_id", f"source '{source_id}' has purpose '{source['purpose']}'",
                   f"choose an enabled source with purpose '{purpose}'")


def import_metrics(conn: sqlite3.Connection, cfg: ClientConfig, path: Path, observed_at: str) -> ImportResult:
    res = ImportResult("metrics", path.name)
    started = utc_now()
    rows = _Rows(path, METRIC_COLS, res)
    sources = {r["source_id"]: r for r in conn.execute("SELECT * FROM sources")}
    funds = {r[0] for r in conn.execute("SELECT fund_id FROM funds")}
    for i, r in rows:
        sid = r["source_id"].strip()
        src = sources.get(sid)
        name = r["metric_name"].strip()
        purpose = "actual_revenue" if name == "actual_revenue" else "fund_metrics"
        try:
            _check_source(src, sid, purpose)
            if r["fund_id"].strip() not in funds:
                raise _Bad("fund_id", f"unknown fund '{r['fund_id']}'", "import the product first")
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
                period_start = _iso_date(r.get("period_start", ""))
                period_end = _iso_date(r.get("period_end", ""))
            except ValueError:
                raise _Bad("as_of_date/effective/available_at/revision", "bad date or revision", "use YYYY-MM-DD and integer revision") from None
            if not as_of:
                raise _Bad("as_of_date", "as_of_date is required", "supply the measurement date")
            if name == "actual_revenue" and (
                not period_start or not period_end or period_start >= period_end
                or not period_start <= as_of < period_end or not r["currency"].strip()
                or unit != "currency_units" or not r["evidence_locator"].strip()
            ):
                raise _Bad("period_start/period_end", "revenue requires a dated period, currency units, currency, and evidence",
                           "supply the inclusive start, exclusive end, and a source locator for earned revenue")
            if not r["external_record_id"].strip():
                raise _Bad("external_record_id", "required for idempotent re-import", "supply a stable id")
        except _Bad as b:
            rows.err(i, b.field, b.msg, b.fix, sid if src is not None else None)
            continue
        obs_id = "obs_" + hashlib.sha256(f"{sid}|{r['external_record_id'].strip()}|{revision}".encode()).hexdigest()[:16]
        record = (r["fund_id"].strip(), name, _canonical(value), norm_unit, r["currency"].strip() or None, scope, basis,
                  as_of, eff_from, eff_to, avail, r["available_at_precision"].strip() or None, period_start, period_end)
        existing = conn.execute("SELECT * FROM metric_observations WHERE obs_id=?", (obs_id,)).fetchone()
        if existing:
            same = (existing["fund_id"], existing["metric_name"], existing["value"], existing["unit"], existing["currency"],
                    existing["scope"], existing["asset_basis"], existing["as_of_date"], existing["effective_from"],
                    existing["effective_to"], existing["available_at"], existing["available_at_precision"],
                    existing["period_start"], existing["period_end"]) == record
            if same:
                res.record("skipped", sid)
            else:
                rows.err(i, "revision", f"revision {revision} of {r['external_record_id']} already stored with different values",
                         "corrections must use a new, higher revision number", sid)
            continue
        with conn:
            conn.execute("INSERT INTO metric_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (obs_id, r["external_record_id"].strip(), sid, record[0], name, record[2], norm_unit, record[4], scope,
                          basis, as_of, eff_from, eff_to, avail, record[11], observed_at,
                          r["evidence_url"].strip() or None, r["evidence_locator"].strip() or None, revision,
                          r["review_status"].strip(), format(raw, "f"), unit, period_start, period_end))
        res.record("inserted", sid)
    _log_run(conn, "metrics", path.name, res, started)
    return res


def import_news(conn: sqlite3.Connection, cfg: ClientConfig, path: Path, observed_at: str) -> ImportResult:
    from .events import detect_events  # local import avoids a cycle

    res = ImportResult("news", path.name)
    started = utc_now()
    rows = _Rows(path, NEWS_COLS, res)
    sources = {r["source_id"]: r for r in conn.execute("SELECT * FROM sources")}
    for i, r in rows:
        sid = r["source_id"].strip()
        src = sources.get(sid)
        try:
            _check_source(src, sid, "news")
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
            rows.err(i, b.field, b.msg, b.fix, sid if src is not None else None)
            continue
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
            res.record("skipped", sid)
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
        res.record("inserted", sid)
    _log_run(conn, "news", path.name, res, started)
    return res
