"""Evidence-linked report assembly, artifacts and analyst approval."""
from __future__ import annotations

import hashlib
import html as html_text
import json
import re
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal as D
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import jinja2

from .artifacts import publish_artifacts, report_paths, saved_context, serialized_manifest, store_bundle
from .config import ClientConfig, project_root
from .db import utc_now
from .events import match_funds
from .feeds import feed_health
from .metrics import compute_metrics, compute_revenue
from .synthesis import add_local_synthesis, extractive_summary
from .taxonomy import select_funds, validated_tags
from .windows import Window, make_window

METHOD_VERSIONS = {"metrics": "decimal_v3", "events": "keyword_rules_v1", "template": "report_v4", "schema": "003"}
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
FEE_LABELS = {"expense_ratio_net": "net expense ratio", "expense_ratio_gross": "gross expense ratio",
              "management_fee": "management fee"}


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
    if not u or re.search(r"[\s\x00-\x1f]", u):
        return None
    try:
        parts = urlsplit(u)
    except ValueError:
        return None
    return u if parts.scheme in {"http", "https"} and parts.hostname and parts.username is None else None


def md_escape(s) -> str:
    value = html_text.escape(str(s if s is not None else ""), quote=False)
    return re.sub(r"([\\|`*\[\]])", r"\\\1", " ".join(value.splitlines()))


def _st(s) -> str:
    return STATE_TEXT.get(s, s)


def _news_window(published, observed, window):
    pub_day = date.fromisoformat(published[:10]) if published else None
    if published and len(published) > 10:
        try:
            instant = datetime.fromisoformat(published)
            if instant.tzinfo is not None:
                pub_day = instant.astimezone(ZoneInfo(window.timezone)).date()
        except ValueError:
            pass
    arrived = observed > window.observed_after if window.observed_after else window.contains_utc(observed)
    inside = pub_day is not None and window.start_local <= pub_day < window.end_local
    late = pub_day is not None and pub_day < window.start_local and arrived
    undated = pub_day is None and arrived
    return inside, late, undated


def build_context(conn, cfg: ClientConfig, window: Window, cutoff: str, profile: str, *,
                  issuer_ids=(), tag_ids=(), pillar_ids=(), request_model=False) -> dict:
    selected = select_funds(conn, cfg, issuer_ids, tag_ids)
    selected_ids = {f["fund_id"] for f in selected}
    if set(pillar_ids) - {p.id for p in cfg.pillars}:
        raise ValueError("unknown report pillar")
    pillars = [p for p in cfg.pillars if not pillar_ids or p.id in pillar_ids]
    filtered = bool(tag_ids or issuer_ids)
    m = compute_metrics(conn, cfg, window, cutoff, funds=selected)
    currency = cfg.report_currency
    fund = {r["fund_id"]: r for r in conn.execute("SELECT * FROM funds")}
    tick_count: dict[str, int] = {}
    for f_ in fund.values():
        tick_count[f_["ticker"]] = tick_count.get(f_["ticker"], 0) + 1
    # a ticker shared by several products is never shown alone (identity needs more than a ticker)
    lab = {i: (f_["ticker"] if tick_count[f_["ticker"]] == 1 else f"{f_['ticker']} [{i}]") for i, f_ in fund.items()}
    obs_ids: set[str] = set()
    raw_revenue = compute_revenue(conn, cfg, window, cutoff, selected_ids)
    obs_ids.update(raw_revenue["obs_ids"])
    revenue = {key: raw_revenue[key] for key in ("coverage", "matched_size", "period", "baseline_period")}
    revenue.update({
        "current": money(raw_revenue["current"], currency) if raw_revenue["current"] is not None else "unavailable",
        "matched_current": money(raw_revenue["matched_current"], currency),
        "matched_baseline": money(raw_revenue["matched_baseline"], currency),
        "change": signed_money(raw_revenue["change"], currency) if raw_revenue["change"] is not None else "unavailable",
        "pct": pct(raw_revenue["pct"]) if raw_revenue["change"] is not None else "unavailable",
    })

    def sel_cell(s, side):
        if s.obs is not None:
            obs_ids.add(s.obs["obs_id"])
        return {"value": s.value, "as_of": s.as_of.isoformat() if s.as_of else None,
                "state": "available" if s.usable else (f"unavailable_{side}" if s.state == "missing" else s.state)}

    assets = []
    for p in m["per_product"]:
        b, c = sel_cell(p["assets_baseline"], "baseline"), sel_cell(p["assets_current"], "current")
        assets.append({"ticker": lab[p["fund_id"]], "name": p["name"],
                       "baseline": money(b["value"], currency) if b["state"] == "available" else _st(b["state"]),
                       "baseline_asof": b["as_of"] or "-",
                       "current": money(c["value"], currency) if c["state"] == "available" else _st(c["state"]),
                       "current_asof": c["as_of"] or "-",
                       "change": signed_money(p["absolute_change"], currency) if p["absolute_change"] is not None else "unavailable",
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
            return {"text": money(s["total"], currency), "asof": s["as_of"].isoformat(), "cov": f"{s['coverage'][0]} of {s['coverage'][1]}"}
        if s["state"] == "unavailable_common_date":
            lo, hi = s["as_of_range"]
            return {"text": "unavailable (observations do not share an as-of date)", "asof": f"{lo} to {hi}", "cov": f"{s['coverage'][0]} of {s['coverage'][1]}"}
        return {"text": "unavailable", "asof": "-", "cov": f"{s['coverage'][0]} of {s['coverage'][1]}"}

    mt, w, px, cn = m["matched"], m["weighted_fee"], m["proxy"], m["counts"]
    matched = {
        "state": mt["state"], "n": mt["coverage"][0], "of": mt["coverage"][1],
        "baseline": money(mt["baseline"]["total"], currency), "current": money(mt["current"]["total"], currency),
        "baseline_asof": mt["baseline"]["as_of"].isoformat() if mt["baseline"].get("as_of") else "-",
        "current_asof": mt["current"]["as_of"].isoformat() if mt["current"].get("as_of") else "-",
        "change": signed_money(mt["absolute_change"], currency) if mt["absolute_change"] is not None else "unavailable",
        "pct": pct(mt["percent_change"]) if mt["absolute_change"] is not None else "unavailable",
        "tickers": [lab[i] for i in mt["cohort"]]}
    weighted = {"state": w["state"], "n": w["coverage_products"][0], "of": w["coverage_products"][1],
                "weight": f"{_q(w['coverage_asset_weight'], 1)}%" if w.get("coverage_asset_weight") is not None else "n/a"}
    if w["state"] == "available":
        weighted.update({"baseline": rate(w["baseline"]), "current": rate(w["current"]), "change": bps(w["change_bps"]),
                         "fee_effect": bps(w["product_fee_effect_bps"]), "mix_effect": bps(w["composition_effect_bps"])})
    proxy = {"state": px["state"]}
    if px["state"] == "available":
        proxy.update({"baseline": money(px["baseline"], currency), "current": money(px["current"], currency),
                      "change": signed_money(px["absolute_change"], currency), "pct": pct(px["percent_change"]), "n": px["n"]})

    # --- events and evidence ---
    ev_rows = conn.execute(
        """SELECT e.*, ev.title, ev.url, ev.published_at, ev.date_precision, ev.source_id, ev.revision AS ev_revision,
                  ev.first_observed_at AS ev_first
           FROM events e JOIN evidence ev ON ev.evidence_id=e.evidence_id
           JOIN sources s ON ev.source_id=s.source_id AND s.internal_report_allowed=1
           WHERE e.review_status != 'rejected' AND e.first_observed_at <= ? ORDER BY ev.published_at, e.event_id""", (cutoff,)).fetchall()
    events, undated, evidence_ids, event_ids = [], [], set(), set()
    for e in ev_rows:
        pub = e["published_at"]
        in_pub, late, no_date = _news_window(pub, e["first_observed_at"], window)
        if not (in_pub or late or no_date):
            continue
        products = [e["fund_id"]] if e["review_status"] == "accepted" and e["fund_id"] else json.loads(e["candidate_fund_ids"])
        if filtered and not selected_ids.intersection(products):
            continue
        status = {"accepted": "accepted", "proposed": "proposed - unreviewed", "needs_review": "needs review (ambiguous or unmatched)",
                  "deferred": "deferred"}[e["review_status"]]
        row = {"event_id": e["event_id"], "type": EVENT_LABELS.get(e["event_type"], e["event_type"]),
               "products": ", ".join(lab[c] for c in products) if products else "unmatched",
               "ambiguous": len(products) != 1, "announced": pub[:10] if pub else "unknown",
               "effective": e["effective_date"] or "not stated in evidence", "status": status,
               "late": late, "title": e["title"], "url": _safe_url(e["url"]), "evidence_id": e["evidence_id"], "source": e["source_id"]}
        (undated if no_date else events).append(row)
        evidence_ids.add(e["evidence_id"]); event_ids.add(e["event_id"])
    launched = [{"ticker": lab[i], "launch_date": fund[i]["launch_date"], "basis": fund[i]["launch_date_basis"]}
                for i in cn["launched"]]
    closed = [{"ticker": lab[i], "closure_date": fund[i]["closure_date"]} for i in cn["closed"]]

    # Preserve unrelated archive coverage and revisions without duplicating event proposals.
    archive = conn.execute(
        """SELECT e.* FROM evidence e JOIN sources s ON e.source_id=s.source_id AND s.internal_report_allowed=1
           WHERE e.first_observed_at<=? AND (
             NOT EXISTS (SELECT 1 FROM evidence earlier JOIN events ev ON earlier.evidence_id=ev.evidence_id
                         WHERE earlier.source_id=e.source_id AND earlier.external_record_id=e.external_record_id)
             OR (e.revision>1 AND e.first_observed_at>?))
           ORDER BY e.revision DESC, e.evidence_id""", (cutoff, window.observed_after or cutoff),
    )
    seen_records = set()
    for row in archive:
        identity = (row["source_id"], row["external_record_id"])
        if identity in seen_records:
            continue
        seen_records.add(identity)
        if not any(_news_window(row["published_at"], row["first_observed_at"], window)):
            continue
        if filtered and not selected_ids.intersection(match_funds(conn, f"{row['title']}\n{row['body'] or ''}")):
            continue
        evidence_ids.add(row["evidence_id"])
    if window.observed_after:
        obs_ids.update(
            r["obs_id"] for r in conn.execute(
                """SELECT m.obs_id,m.fund_id FROM metric_observations m JOIN sources s ON s.source_id=m.source_id
                   WHERE m.revision>1 AND m.first_observed_at>? AND m.first_observed_at<=?
                     AND m.as_of_date<? AND m.review_status='approved' AND s.internal_report_allowed=1""",
                (window.observed_after, cutoff, window.end_local.isoformat()),
            ) if r["fund_id"] in selected_ids
        )

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
        note = [f"revision {r['revision']}", f"{r['scope']} scope", r["evidence_locator"] or "no locator"]
        if r["currency"]:
            note.append(r["currency"])
        if r["available_at"]:
            note.append(f"source availability {r['available_at']}")
        if r["period_start"] and r["period_end"]:
            note.append(f"period {r['period_start']} to {r['period_end']} exclusive")
        register.append({"id": oid, "kind": "metric", "source": r["source_id"],
                         "title": f"{lab[r['fund_id']]} {r['metric_name']} = {r['value_original']} {r['unit_original']}",
                         "url": _safe_url(r["evidence_url"]), "date": r["as_of_date"], "first_observed": r["first_observed_at"],
                         "note": ", ".join(note)})

    pending = conn.execute("SELECT COUNT(*) FROM events WHERE review_status IN ('proposed','needs_review','deferred')").fetchone()[0]
    sources = []
    health = feed_health(conn, cutoff)
    for s in conn.execute("SELECT * FROM sources ORDER BY source_id"):
        sources.append({"id": s["source_id"], "type": s["source_type"], "enabled": bool(s["enabled"]),
                        "purpose": s["purpose"] or "unspecified", "frequency": s["update_frequency"] or "manual",
                        "permission": s["permission_status"], "notes": s["coverage_notes"], "feed": health.get(s["source_id"])})
    limitations = [
        "News and events cover only items imported from the listed sources; this is not exhaustive market activity.",
        "Net-assets changes reflect markets, subscriptions/redemptions and distributions; they are not net flows.",
        "Event rows are keyword proposals until a reviewer accepts them; none was produced by an AI model.",
    ]
    if cfg.mode == "demo":
        limitations.insert(0, "All data in this report is synthetic demonstration data.")
    if not m["universe_size"]:
        limitations.append("No approved products match the tracked subset. Financial observations and lifecycle coverage are unavailable.")
    if not any(s["enabled"] for s in sources):
        limitations.append("No sources are enabled for import. Review the source status and coverage notes below.")
    incomplete = [s["id"] for s in sources if s["enabled"] and s["type"] == "rss"
                  and (s["feed"] is None or s["feed"]["status"] == "failed")]
    if incomplete:
        limitations.append("Feed coverage is incomplete for " + ", ".join(incomplete) + ".")
    if pending:
        limitations.append(f"{pending} event proposal(s) in the database are not yet accepted; ambiguous matches are excluded from product-level claims.")
    if cn["proxy_current"]:
        limitations.append(f"{cn['proxy_current']} active product(s) rely on an inception-date proxy for launch date; counts are labeled accordingly.")
    if cn["unknown_lifecycle"]:
        limitations.append("Products with unknown launch date are excluded from counts: " + ", ".join(cn["unknown_lifecycle"]))
    if mt["coverage"][0] < mt["coverage"][1]:
        limitations.append(f"Matched-cohort comparison covers {mt['coverage'][0]} of {mt['coverage'][1]} products active at the current date; others lack compatible observations at both dates.")
    if w["state"] == "unavailable_common_date":
        limitations.append("The asset-weighted fee requires a common asset measurement date for the paired products at each endpoint.")
    if px["state"] != "available":
        limitations.append("The annualized expense-based proxy requires compatible fund net assets and net expense ratios at both endpoints.")
    if window.lookback == "full_history":
        limitations.append("Full history starts with available archived observations and lifecycle records. Coverage can have gaps.")
    if window.observed_after:
        limitations.append(f"The previous run cutoff was {window.observed_after}. Newly observed late evidence and revisions are included.")
    if raw_revenue["coverage"] < len(selected):
        limitations.append("Actual revenue coverage requires observed product revenue for the exact reporting period.")

    identity = [profile, window.lookback, window.start_local.isoformat(), window.end_local.isoformat(), cfg.report_mode, cutoff, cfg.client_id]
    if filtered or pillar_ids or request_model:
        identity.append(json.dumps([sorted(issuer_ids), sorted(tag_ids), sorted(pillar_ids), request_model]))
    rid = "rpt_" + hashlib.sha256("|".join(identity).encode()).hexdigest()[:12]
    universe = {"country": cfg.universe.listing_country, "type": cfg.universe.product_type,
                "issuers": sorted(issuer_ids) if issuer_ids else cfg.universe.issuer_ids, "size": m["universe_size"],
                "tags": sorted(tag_ids)}
    context = {
        "report_id": rid, "status": "draft", "banner": cfg.demo_banner, "client": cfg.client_display_name, "profile": profile,
        "lookback": window.lookback, "mode": cfg.report_mode, "timezone": window.timezone, "cutoff": cutoff,
        "window": {"start": window.start_local.isoformat(), "end_exclusive": window.end_local.isoformat(),
                   "start_utc": window.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "end_utc": window.end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "baseline": window.baseline_date.isoformat(), "current": window.current_date.isoformat()},
        "universe": universe, "currency": currency, "fee_label": FEE_LABELS[cfg.primary_fee_metric],
        "pillars": [{"id": p.id, "label": p.label} for p in pillars],
        "selected_products": {f["fund_id"]: f["name"] for f in selected},
        "counts": {"baseline": cn["baseline"], "current": cn["current"], "change": f"{cn['change']:+d}",
                   "proxy_baseline": cn["proxy_baseline"], "proxy_current": cn["proxy_current"]},
        "launched": launched, "closed": closed, "events": events, "undated": undated,
        "snapshot_baseline": snap(m["snapshot_baseline"]), "snapshot_current": snap(m["snapshot_current"]),
        "assets": assets, "matched": matched, "fees": fees, "weighted": weighted, "proxy": proxy, "revenue": revenue,
        "chart": {"baseline": mt["baseline"]["total"], "current": mt["current"]["total"]},
        "sources": sources, "limitations": limitations, "register": register, "pending_reviews": pending,
        "manifest": {"report_id": rid, "mode": cfg.report_mode, "lookback": window.lookback, "window_utc": [window.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), window.end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")],
                     "data_cutoff": cutoff, "observation_ids": sorted(obs_ids), "evidence_ids": sorted(evidence_ids),
                     "event_ids": sorted(event_ids), "method_versions": METHOD_VERSIONS,
                     "universe": universe, "report_currency": currency, "primary_fee_metric": cfg.primary_fee_metric,
                     "pillars": [p.id for p in pillars], "observed_after": window.observed_after, "status": "draft",
                     "config_hash": hashlib.sha256(json.dumps(cfg.model_dump(mode="json", exclude={"root"}), sort_keys=True).encode()).hexdigest()[:16],
                     "generated_by": "etf_pilot template renderer"},
    }
    context["synthesis"] = extractive_summary(context)
    return context


def _env(autoescape: bool) -> jinja2.Environment:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(project_root() / "templates"), autoescape=autoescape,
                             trim_blocks=True, lstrip_blocks=True, undefined=jinja2.StrictUndefined)
    env.filters["mdx"] = md_escape
    env.filters["mdurl"] = lambda url: quote(url, safe=":/?&=+%#@;!,~*'-._")
    return env


def render(ctx: dict) -> tuple[str, str]:
    return _env(False).get_template("report.md.j2").render(r=ctx), _env(True).get_template("report.html.j2").render(r=ctx)


def _coverage_start(conn, cfg, end_date, cutoff, issuer_ids, tag_ids) -> date:
    funds = select_funds(conn, cfg, issuer_ids, tag_ids)
    ids = {fund["fund_id"] for fund in funds}
    days = {fund["launch_date"] for fund in funds if fund["launch_date"]}
    days.update(row["earliest"] for row in conn.execute(
        """SELECT m.fund_id,min(coalesce(m.period_start,m.as_of_date)) AS earliest
           FROM metric_observations m JOIN sources s ON s.source_id=m.source_id
           WHERE m.first_observed_at<=? AND m.review_status='approved' AND s.internal_report_allowed=1 GROUP BY m.fund_id""",
        (cutoff,),
    ) if row["fund_id"] in ids)
    for row in conn.execute(
        """SELECT e.title,e.body,coalesce(e.published_at,e.first_observed_at) AS start
           FROM evidence e JOIN sources s ON s.source_id=e.source_id
           WHERE e.first_observed_at<=? AND s.internal_report_allowed=1""", (cutoff,),
    ):
        if not (issuer_ids or tag_ids) or ids.intersection(match_funds(conn, f"{row['title']}\n{row['body'] or ''}")):
            days.add(row["start"][:10])
    available = [day for day in days if day < end_date.isoformat()]
    if not available:
        raise ValueError("Full history needs archived records for the selected universe before the end date.")
    return date.fromisoformat(min(available))


def _cutoff_utc(value: str) -> str:
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is not None:
            return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        pass
    raise ValueError("use a timezone-aware data cutoff such as YYYY-MM-DDTHH:MM:SSZ")


def _definition_id(cfg, issuer_ids, tag_ids, pillar_ids, request_model):
    definition = [
        METHOD_VERSIONS, cfg.model_dump(mode="json", exclude={"root", "database_path", "export_dir"}),
        sorted(issuer_ids or cfg.universe.issuer_ids), sorted(tag_ids),
        sorted(pillar_ids or [pillar.id for pillar in cfg.pillars]), request_model,
    ]
    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()[:20]


def generate_report(conn, cfg: ClientConfig, lookback: str, end_date: date, cutoff: str, profile: str = "default",
                    start_date: date | None = None, *, issuer_ids=(), tag_ids=(), pillar_ids=(),
                    request_model: bool = False) -> dict:
    cutoff = _cutoff_utc(cutoff)
    issuer_ids = tuple(sorted(set(issuer_ids)))
    tag_ids = validated_tags(cfg, tag_ids)
    pillar_ids = tuple(sorted(set(pillar_ids)))
    definition = _definition_id(cfg, issuer_ids, tag_ids, pillar_ids, request_model)
    observed_after = None
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if lookback == "last_run":
            existing = conn.execute(
                """SELECT report_id FROM reports WHERE window_end=? AND data_cutoff=? AND profile=?
                   AND json_extract(snapshot_json,'$.lookback')='last_run'
                   AND json_extract(snapshot_json,'$.manifest.definition_id')=?""",
                (end_date.isoformat(), cutoff, profile, definition),
            ).fetchone()
            if existing:
                rid = existing["report_id"]
                return {"report_id": rid, **report_paths(cfg, rid), "context": saved_context(conn, rid)}
            checkpoint = conn.execute("SELECT * FROM report_checkpoints WHERE definition_id=?", (definition,)).fetchone()
            if checkpoint:
                start_date = date.fromisoformat(checkpoint["end_date"])
                observed_after = checkpoint["data_cutoff"]
                if cutoff < observed_after or end_date <= start_date:
                    raise ValueError("Since last briefing needs a later end date and a cutoff at or after the previous run.")
            elif start_date is None:
                raise ValueError("Since last briefing needs a successful previous run with these filters or an initial start date.")
        elif lookback == "full_history":
            start_date = _coverage_start(conn, cfg, end_date, cutoff, issuer_ids, tag_ids)
        window = make_window(lookback, end_date, cfg.report_timezone, start_date, observed_after=observed_after)
        ctx = build_context(conn, cfg, window, cutoff, profile, issuer_ids=issuer_ids, tag_ids=tag_ids,
                            pillar_ids=pillar_ids, request_model=request_model)
        rid = ctx["report_id"]
        existing = conn.execute("SELECT status FROM reports WHERE report_id=?", (rid,)).fetchone()
        if existing and existing["status"] != "draft":
            return {"report_id": rid, **report_paths(cfg, rid), "context": saved_context(conn, rid)}
        if request_model:
            add_local_synthesis(conn, cfg, ctx)
        ctx["manifest"]["definition_id"] = definition
        ctx["manifest"]["synthesis"] = ctx["synthesis"]
        md, html = render(ctx)
        bundle = {"markdown": md, "html": html, "manifest": serialized_manifest(ctx)}
        conn.execute(
            """INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(report_id)
               DO UPDATE SET snapshot_json=excluded.snapshot_json""",
            (rid, profile, cfg.report_mode, window.start_local.isoformat(), window.end_local.isoformat(), cutoff,
             "draft", utc_now(), json.dumps(ctx, default=str, sort_keys=True)),
        )
        store_bundle(conn, rid, bundle)
        conn.execute(
            """INSERT INTO report_checkpoints VALUES (?,?,?,?) ON CONFLICT(definition_id) DO UPDATE
               SET end_date=excluded.end_date, data_cutoff=excluded.data_cutoff, report_id=excluded.report_id
               WHERE excluded.end_date >= report_checkpoints.end_date AND excluded.data_cutoff >= report_checkpoints.data_cutoff""",
            (definition, window.end_local.isoformat(), cutoff, rid),
        )
        with publish_artifacts(cfg, rid, bundle):
            conn.commit()
    return {"report_id": rid, **report_paths(cfg, rid), "context": ctx}
