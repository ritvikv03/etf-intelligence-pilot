"""Review queue: accept / reject / defer event proposals with an audit trail."""
from __future__ import annotations

import json

from .db import utc_now

DECISIONS = {"accept": "accepted", "reject": "rejected", "defer": "deferred"}


def list_pending(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT e.event_id, e.event_type, e.review_status, e.candidate_fund_ids, ev.title, ev.published_at, ev.evidence_id
           FROM events e JOIN evidence ev ON ev.evidence_id=e.evidence_id
           WHERE e.review_status IN ('proposed','needs_review','deferred') ORDER BY e.event_id""").fetchall()
    return [dict(r) for r in rows]


def decide(conn, event_id: str, decision: str, reviewer: str, reason: str = "", fund_id: str | None = None,
           effective_date: str | None = None, now: str | None = None) -> None:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
    ev = conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
    if ev is None:
        raise ValueError(f"unknown event {event_id}")
    if decision == "accept":
        resolved = fund_id or ev["fund_id"]
        if not resolved:
            raise ValueError("ambiguous or unmatched event: pass --fund-id to resolve identity before accepting")
        if resolved not in json.loads(ev["candidate_fund_ids"]) and not conn.execute("SELECT 1 FROM funds WHERE fund_id=?", (resolved,)).fetchone():
            raise ValueError(f"unknown fund {resolved}")
    else:
        resolved = ev["fund_id"]
    at = now or utc_now()
    prev = {"review_status": ev["review_status"], "fund_id": ev["fund_id"], "effective_date": ev["effective_date"]}
    new = {"review_status": DECISIONS[decision], "fund_id": resolved, "effective_date": effective_date or ev["effective_date"]}
    with conn:
        conn.execute("UPDATE events SET review_status=?, fund_id=?, effective_date=?, approved_at=? WHERE event_id=?",
                     (new["review_status"], resolved, new["effective_date"], at if decision == "accept" else None, event_id))
        if decision == "accept" and resolved:
            conn.execute("UPDATE events SET candidate_fund_ids=? WHERE event_id=?", (json.dumps([resolved]), event_id))
        conn.execute("INSERT INTO review_actions(entity_type,entity_id,reviewer,decision,reason,previous_value,new_value,at) VALUES ('event',?,?,?,?,?,?,?)",
                     (event_id, reviewer, decision, reason, json.dumps(prev), json.dumps(new), at))
