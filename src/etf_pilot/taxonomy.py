"""Analyst-maintained product taxonomy and composite report selection."""
from __future__ import annotations

import json

from .config import ClientConfig
from .db import utc_now


def validated_tags(cfg: ClientConfig, tag_ids) -> tuple[str, ...]:
    requested = set(tag_ids)
    missing = requested - {tag.id for tag in cfg.taxonomy}
    if missing:
        raise ValueError("unknown taxonomy IDs: " + ", ".join(sorted(missing)))
    return tuple(sorted(requested))


def product_tags(conn) -> dict[str, set[str]]:
    result = {}
    for row in conn.execute("SELECT fund_id, tag_id FROM product_tags"):
        result.setdefault(row["fund_id"], set()).add(row["tag_id"])
    return result


def replace_tags(conn, fund_id: str, tag_ids) -> None:
    conn.execute("DELETE FROM product_tags WHERE fund_id=?", (fund_id,))
    conn.executemany("INSERT INTO product_tags VALUES (?,?)", [(fund_id, tag) for tag in tag_ids])


def review_tags(conn, cfg: ClientConfig, fund_id: str, tag_ids, reviewer: str) -> None:
    tags = validated_tags(cfg, tag_ids)
    if not reviewer.strip():
        raise ValueError("a reviewer is required")
    if not conn.execute("SELECT 1 FROM funds WHERE fund_id=?", (fund_id,)).fetchone():
        raise ValueError("unknown fund")
    previous = sorted(row[0] for row in conn.execute("SELECT tag_id FROM product_tags WHERE fund_id=?", (fund_id,)))
    now = utc_now()
    with conn:
        replace_tags(conn, fund_id, tags)
        conn.execute(
            """INSERT INTO tag_reviews VALUES (?,?,?) ON CONFLICT(fund_id)
               DO UPDATE SET reviewer=excluded.reviewer, reviewed_at=excluded.reviewed_at""",
            (fund_id, reviewer.strip(), now),
        )
        conn.execute(
            """INSERT INTO review_actions(entity_type,entity_id,reviewer,decision,previous_value,new_value,at)
               VALUES ('tags',?,?,'set',?,?,?)""",
            (fund_id, reviewer.strip(), json.dumps(previous), json.dumps(tags), now),
        )


def select_funds(conn, cfg: ClientConfig, issuer_ids=(), tag_ids=()):
    tags = set(validated_tags(cfg, tag_ids))
    issuers = set(issuer_ids) if issuer_ids else set(cfg.universe.issuer_ids)
    if issuers - set(cfg.universe.issuer_ids):
        raise ValueError("issuer filter is outside the configured universe")
    parents = {tag.id: tag.parent_id for tag in cfg.taxonomy}
    assigned = product_tags(conn) if tags else {}

    def matches(fund):
        if not tags:
            return True
        inherited = set()
        for leaf in assigned.get(fund["fund_id"], ()):
            tag_id = leaf
            while tag_id in parents and tag_id not in inherited:
                inherited.add(tag_id)
                tag_id = parents[tag_id]
        return tags <= inherited

    return [
        fund for fund in conn.execute("SELECT * FROM funds WHERE review_status='approved' ORDER BY fund_id")
        if fund["listing_country"] == cfg.universe.listing_country
        and fund["product_type"] == cfg.universe.product_type
        and fund["issuer_id"] in issuers and matches(fund)
    ]
