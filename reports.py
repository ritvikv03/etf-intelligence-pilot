"""Deterministic report assembly and Markdown/HTML/JSON export. No model is involved."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal as D
from pathlib import Path

import jinja2

from .config import ClientConfig, project_root
from .db import utc_now
from .metrics import compute_metrics
from .windows import Window, make_window

METHOD_VERSIONS = {"metrics": "decimal_v1", "events": "keyword_rules_v1", "template": "report_v1", "schema": "001"}
STATE_TEXT = {
    "available": "available", "unavailable_baseline": "baseline unavailable", "unavailable_current": "current unavailable",
    "not_active": "not active at date", "stale": "stale (older than policy)", "unapproved": "unapproved",
    "incompatible_scope": "incompatible scope", "incompatible_currency": "incompatible currency",
    "incompatible_basis": "not net-asset basis", "unavailable_common_date": "no common as-of date",
    "fee_asset_date_gap": "fee/asset dates too far apart", "outside_effective_interval": "outside fee effective interval",
}
EVENT_LABELS = {"launch_announced": "Launch announced", "closure_announced": "Closure announced",
                "fee_change_announced": "Fee change announced", "conversion": "Conversion", "rename": "Rename",
                "mandate_change": "Mandate change", "index_change": "Index change"}


def _q(d: D, places: int) -> D:
    return d.quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP)


def money(d, cur="USD") -> str:
    return "n/a" if d is None else f"{cur} {_q(d, 0):,}"


def signed_money(d, cur="USD") -> str:
    return "n/a" if d is None else f"{'+' if d > 0 else ''}{cur} {_q(d, 0):,}"


def pct(d) -> str:
    return "N/A" if d is None else f"{'+' if d > 0 else ''}{_q(d, 2)}%"


def rate(d) -> str:  # annual decimal -> percent display, 4 dp
    return "n/a" if d is None else f"{_q(d * 100, 4)}%"


def bps(d) -> str:
    return "n/a" if d is None else f"{'+' if d > 0 else ''}{_q(d, 1)} bp"


def _safe_url(u):
    return u if u and re.match(r"^https?://", u) else None


def md_escape(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def _st(s) -> str:
    return STATE_TEXT.get(s, s)


def build_context(conn, cfg: ClientConfig, window: Window, cutoff: str, profile: str) -> dict:
    m = compute_metrics(conn, cfg, window, cutoff)
    fund = {r["fund_id"]: r for r in conn.execute("SELECT * FROM funds")}
    tick_count: dict[str, int] = {}
    for f_ in fund.values():
        tick_count[f_["ticker"]] = tick_count.get(f_["ticker"], 0) + 1
    # a ticker shared by several products is never shown alone (identity needs more than a ticker)
    lab = {i: (f_["ticker"] if tick_count[f_["ticker"]] == 1 else f"{f_['ticker']} [{i}]") for i, f_ in fund.items()}
    obs_ids: set[str] = set()

    def sel_cell(s, side):
        if s.obs is not None:
            obs_ids.add(s.obs["obs_id"])
        return {"value": s.value, "as_of": s.as_of.isoformat() if s.as_of else None,
                "state": "available" if s.usable else (f"unavailable_{side}" if s.state == "missing" else s.state)}

    assets = []
    for p in m["per_product"]:
        b, c = sel_cell(p["assets_baseline"], "baseline"), sel_cell(p["assets_current"], "current")
        assets.append({"ticker": lab[p["fund_id"]], "name": p["name"],
                       "baseline": money(b["value"]) if b["state"] == "available" else _st(b["state"]),
                       "baseline_asof": b["as_of"] or "-",
                       "current": money(c["value"]) if c["state"] == "available" else _st(c["state"]),
                       "current_asof": c["as_of"] or "-",
                       "change": signed_money(p["absolute_change"]) if p["absolute_change"] is not None else "unavailable",
                       "pct": pct(p["percent_change"]) if p["absolute_change"] is not None else "unavailable",
                       "cohort": "yes" if p["in_matched_cohort"] else "no"})
    fees = []
    for f in m["fees"]:
        b, c = sel_cell(f["baseline"], "baseline"), sel_cell(f["current"], "current")
        fees.append({"ticker": lab[f["fund_id"]],
                     "baseline": rate(b["value"]) if b["state"] == "available" else _st(b["state"]),
                     "current": rate(c["value"]) if c["state"] == "available" else _st(c["state"]),
                     "change": bps(f["bps_change"]) if f["bps_change"] is not None else "unavailable"})

    def snap(s):
        if s["state"] == "available":
            return {"text": money(s["total"]), "asof": s["as_of"].isoformat(), "cov": f"{s['coverage'][0]} of {s['coverage'][1]}"}
        if s["state"] == "unavailable_common_date":
            lo, hi = s["as_of_range"]
            return {"text": "unavailable (observations do not share an as-of date)", "asof": f"{lo} to {hi}", "cov": f"{s['coverage'][0]} of {s['coverage'][1]}"}
        return {"text": "unavailable", "asof": "-", "cov": f"{s['coverage'][0]} of {s['coverage'][1]}"}

    mt, w, px, cn = m["matched"], m["weighted_fee"], m["proxy"], m["counts"]
    matched = {
        "state": mt["state"], "n": mt["coverage"][0], "of": mt["coverage"][1],
        "baseline": money(mt["baseline"]["total"]), "current": money(mt["current"]["total"]),
        "baseline_asof": mt["baseline"]["as_of"].isoformat() if mt["baseline"].get("as_of") else "-",
        "current_asof": mt["current"]["as_of"].isoformat() if mt["current"].get("as_of") else "-",
        "change": signed_money(mt["absolute_change"]) if mt["absolute_change"] is not None else "unavailable",
        "pct": pct(mt["percent_change"]) if mt["absolute_change"] is not None else "unavailable",
        "tickers": [lab[i] for i in mt["cohort"]]}
    weighted = {"state": w["state"], "n": w["coverage_products"][0], "of": w["coverage_products"][1],
                "weight": f"{_q(w['coverage_asset_weight'], 1)}%" if w.get("coverage_asset_weight") is not None else "n/a"}
    if w["state"] == "available":
        weighted.update({"baseline": rate(w["baseline"]), "current": rate(w["current"]), "change": bps(w["change_bps"]),
                         "fee_effect": bps(w["product_fee_effect_bps"]), "mix_effect": bps(w["composition_effect_bps"])})
    proxy = {"state": px["state"]}
    if px["state"] == "available":
        proxy.update({"baseline": money(px["baseline"]), "current": money(px["current"]),
                      "change": signed_money(px["absolute_change"]), "pct": pct(px["percent_change"]), "n": px["n"]})

    # --- events and evidence ---
    ev_rows = conn.execute(
        """SELECT e.*, ev.title, ev.url, ev.published_at, ev.date_precision, ev.source_id, ev.revision AS ev_revision,
                  ev.first_observed_at AS ev_first
           FROM events e JOIN evidence ev ON ev.evidence_id=e.evidence_id
           WHERE e.review_status != 'rejected' AND e.first_observed_at <= ? ORDER BY ev.published_at, e.event_id""", (cutoff,)).fetchall()
    events, undated, evidence_ids, event_ids = [], [], set(), set()
    for e in ev_rows:
        pub = e["published_at"]
        in_pub = bool(pub) and window.start_local <= date.fromisoformat(pub[:10]) < window.end_local
        late = bool(pub) and date.fromisoformat(pub[:10]) < window.start_local and window.contains_utc(e["first_observed_at"])
        no_date = not pub and window.contains_utc(e["first_observed_at"])
        if not (in_pub or late or no_date):
            continue
        cands = json.loads(e["candidate_fund_ids"])
        status = {"accepted": "accepted", "proposed": "proposed - unreviewed", "needs_review": "needs review (ambiguous or unmatched)",
                  "deferred": "deferred"}[e["review_status"]]
        row = {"event_id": e["event_id"], "type": EVENT_LABELS.get(e["event_type"], e["event_type"]),
               "products": ", ".join(lab[c] for c in cands) if cands else "unmatched",
               "ambiguous": len(cands) != 1, "announced": pub[:10] if pub else "unknown",
               "effective": e["effective_date"] or "not stated in evidence", "status": status,
               "late": late, "title": e["title"], "url": _safe_url(e["url"]), "evidence_id": e["evidence_id"], "source": e["source_id"]}
        (undated if no_date else events).append(row)
        evidence_ids.add(e["evidence_id"]); event_ids.add(e["event_id"])
    launched = [{"ticker": lab[i], "launch_date": fund[i]["launch_date"], "basis": fund[i]["launch_date_basis"]}
                for i in cn["launched"]]
    closed = [{"ticker": lab[i], "closure_date": fund[i]["closure_date"]} for i in cn["closed"]]

    # evidence register
    register = []
    for eid in sorted(evidence_ids):
        r = conn.execute("SELECT * FROM evidence WHERE evidence_id=?", (eid,)).fetchone()
        assoc = conn.execute("SELECT source_id FROM evidence_associations WHERE evidence_id=? ORDER BY source_id", (eid,)).fetchall()
        register.append({"id": eid, "kind": "news", "source": ", ".join(a[0] for a in assoc), "title": r["title"],
                         "url": _safe_url(r["url"]), "date": (r["published_at"] or "unknown")[:10],
                         "first_observed": r["first_observed_at"], "note": f"revision {r['revision']}"})
    for oid in sorted(obs_ids):
        r = conn.execute("SELECT * FROM metric_observations WHERE obs_id=?", (oid,)).fetchone()
        register.append({"id": oid, "kind": "metric", "source": r["source_id"],
                         "title": f"{lab[r['fund_id']]} {r['metric_name']} = {r['value_original']} {r['unit_original']}",
                         "url": _safe_url(r["evidence_url"]), "date": r["as_of_date"], "first_observed": r["first_observed_at"],
                         "note": f"revision {r['revision']}; {r['evidence_locator'] or 'no locator'}"})

    pending = conn.execute("SELECT COUNT(*) FROM events WHERE review_status IN ('proposed','needs_review','deferred')").fetchone()[0]
    sources = []
    for s in conn.execute("SELECT * FROM sources ORDER BY source_id"):
        run = conn.execute("SELECT * FROM ingestion_runs WHERE kind IN ('news','metrics') ORDER BY run_id DESC LIMIT 1").fetchone()
        sources.append({"id": s["source_id"], "type": s["source_type"], "enabled": bool(s["enabled"]),
                        "permission": s["permission_status"], "notes": s["coverage_notes"]})
    limitations = [
        "News and events cover only items imported from the listed sources; this is not exhaustive market activity.",
        "Net-assets changes reflect markets, subscriptions/redemptions and distributions; they are not net flows.",
        "Event rows are keyword proposals until a reviewer accepts them; none was produced by an AI model.",
    ]
    if cfg.mode == "demo":
        limitations.insert(0, "All data in this report is synthetic demonstration data.")
    if pending:
        limitations.append(f"{pending} event proposal(s) in the database are not yet accepted; ambiguous matches are excluded from product-level claims.")
    if cn["proxy_current"]:
        limitations.append(f"{cn['proxy_current']} active product(s) rely on an inception-date proxy for launch date; counts are labeled accordingly.")
    if cn["unknown_lifecycle"]:
        limitations.append("Products with unknown launch date are excluded from counts: " + ", ".join(cn["unknown_lifecycle"]))
    if mt["coverage"][0] < mt["coverage"][1]:
        limitations.append(f"Matched-cohort comparison covers {mt['coverage'][0]} of {mt['coverage'][1]} products active at the current date; others lack compatible observations at both dates.")
    if not px["state"] == "available":
        limitations.append("Annualized expense-based proxy is unavailable (disabled or no compatible fee/asset pairs).")
    limitations.append("Themes, tags and competitor taxonomy are not implemented in this milestone; no theme conclusions are drawn.")

    rid = "rpt_" + hashlib.sha256("|".join([profile, window.lookback, window.start_local.isoformat(), window.end_local.isoformat(),
                                             cfg.report_mode, cutoff, cfg.client_id]).encode()).hexdigest()[:12]
    return {
        "report_id": rid, "status": "draft", "banner": cfg.demo_banner, "client": cfg.client_display_name, "profile": profile,
        "lookback": window.lookback, "mode": cfg.report_mode, "timezone": window.timezone, "cutoff": cutoff,
        "window": {"start": window.start_local.isoformat(), "end_exclusive": window.end_local.isoformat(),
                   "start_utc": window.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "end_utc": window.end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "baseline": window.baseline_date.isoformat(), "current": window.current_date.isoformat()},
        "universe": {"country": cfg.universe.listing_country, "type": cfg.universe.product_type,
                     "issuers": cfg.universe.issuer_ids, "size": m["universe_size"]},
        "pillars": [{"id": p.id, "label": p.label} for p in cfg.pillars],
        "counts": {"baseline": cn["baseline"], "current": cn["current"], "change": f"{cn['change']:+d}",
                   "proxy_baseline": cn["proxy_baseline"], "proxy_current": cn["proxy_current"]},
        "launched": launched, "closed": closed, "events": events, "undated": undated,
        "snapshot_baseline": snap(m["snapshot_baseline"]), "snapshot_current": snap(m["snapshot_current"]),
        "assets": assets, "matched": matched, "fees": fees, "weighted": weighted, "proxy": proxy,
        "sources": sources, "limitations": limitations, "register": register, "pending_reviews": pending,
        "manifest": {"report_id": rid, "mode": cfg.report_mode, "lookback": window.lookback, "window_utc": [window.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), window.end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")],
                     "data_cutoff": cutoff, "observation_ids": sorted(obs_ids), "evidence_ids": sorted(evidence_ids),
                     "event_ids": sorted(event_ids), "method_versions": METHOD_VERSIONS,
                     "config_hash": hashlib.sha256(json.dumps(cfg.model_dump(mode="json", exclude={"root"}), sort_keys=True).encode()).hexdigest()[:16],
                     "generated_by": "etf_pilot template renderer (no AI model)"},
    }


def _env(autoescape: bool) -> jinja2.Environment:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(project_root() / "templates"), autoescape=autoescape,
                             trim_blocks=True, lstrip_blocks=True, undefined=jinja2.StrictUndefined)
    env.filters["mdx"] = md_escape
    return env


def render(ctx: dict) -> tuple[str, str]:
    return _env(False).get_template("report.md.j2").render(r=ctx), _env(True).get_template("report.html.j2").render(r=ctx)


def generate_report(conn, cfg: ClientConfig, lookback: str, end_date: date, cutoff: str, profile: str = "default",
                    start_date: date | None = None) -> dict:
    window = make_window(lookback, end_date, cfg.report_timezone, start_date)
    ctx = build_context(conn, cfg, window, cutoff, profile)
    md, html = render(ctx)
    out = cfg.export_path
    out.mkdir(parents=True, exist_ok=True)
    rid = ctx["report_id"]
    (out / f"{rid}.md").write_text(md, encoding="utf-8")
    (out / f"{rid}.html").write_text(html, encoding="utf-8")
    (out / f"{rid}.manifest.json").write_text(json.dumps(ctx["manifest"], indent=2, sort_keys=True), encoding="utf-8")
    with conn:
        conn.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET snapshot_json=excluded.snapshot_json "
                     "WHERE reports.status='draft'",
                     (rid, profile, cfg.report_mode, window.start_local.isoformat(), window.end_local.isoformat(), cutoff, "draft",
                      utc_now(), json.dumps(ctx, default=str, sort_keys=True)))
    return {"report_id": rid, "markdown": out / f"{rid}.md", "html": out / f"{rid}.html", "manifest": out / f"{rid}.manifest.json", "context": ctx}
