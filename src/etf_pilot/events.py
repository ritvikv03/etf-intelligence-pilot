"""Keyword event proposals and conservative fund matching. Proposals are never authoritative."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

EVENT_RULES = [
    ("launch_announced", re.compile(r"\b(launch(es|ed|ing)?|introduc(es|ed|ing)|debut(s|ed)?)\b", re.I)),
    ("closure_announced", re.compile(r"\b(liquidat\w*|closure|clos(es|ing) (the )?(fund|etf))\b", re.I)),
    ("fee_change_announced", re.compile(r"(expense ratio|fee (cut|reduction|waiver)|(lower|reduc\w+|cut\w*) (its |the )?(net |gross )?(expense|management|fee))", re.I)),
    ("conversion", re.compile(r"\bconver(t|ts|ted|sion)\b", re.I)),
    ("rename", re.compile(r"\b(renam\w+|name change)\b", re.I)),
    ("mandate_change", re.compile(r"\b(mandate|investment objective) (change|update)\w*", re.I)),
    ("index_change", re.compile(r"\b(new|change\w* (its |the )?)index\b", re.I)),
]


def match_funds(conn: sqlite3.Connection, text: str) -> list[str]:
    """Ticker token first, then full fund name. Returns every candidate (ambiguity is preserved)."""
    funds = conn.execute("SELECT fund_id, name, ticker FROM funds WHERE review_status != 'rejected'").fetchall()
    tokens = set(re.findall(r"\b[A-Z][A-Z0-9.]{1,5}\b", text))
    by_ticker = sorted({f["fund_id"] for f in funds if f["ticker"] in tokens})
    if by_ticker:
        return by_ticker
    low = text.lower()
    return sorted({f["fund_id"] for f in funds if f["name"].lower() in low})


def detect_events(conn: sqlite3.Connection, evidence_id: str, title: str, body: str, observed_at: str) -> list[str]:
    text = f"{title}\n{(body or '')[:300]}"
    candidates = match_funds(conn, text)
    prior = conn.execute(
        """SELECT e2.event_type, e2.candidate_fund_ids FROM evidence e1
           JOIN evidence e0 ON e0.source_id=e1.source_id AND e0.external_record_id=e1.external_record_id AND e0.evidence_id != e1.evidence_id
           JOIN events e2 ON e2.evidence_id=e0.evidence_id WHERE e1.evidence_id=?""", (evidence_id,)).fetchall()
    seen = {(p["event_type"], p["candidate_fund_ids"]) for p in prior}
    created = []
    for etype, rx in EVENT_RULES:
        if not rx.search(text):
            continue
        cand_json = json.dumps(candidates)
        if (etype, cand_json) in seen:  # a revised article is not a second event
            continue
        eid = "evt_" + hashlib.sha256(f"{evidence_id}|{etype}".encode()).hexdigest()[:16]
        single = len(candidates) == 1
        conn.execute(
            "INSERT OR IGNORE INTO events(event_id,evidence_id,event_type,fund_id,candidate_fund_ids,effective_date,"
            "first_observed_at,proposed_by,review_status) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, evidence_id, etype, candidates[0] if single else None, cand_json, None, observed_at, "keyword_rules_v1",
             "proposed" if single else "needs_review"))
        created.append(eid)
    return created
