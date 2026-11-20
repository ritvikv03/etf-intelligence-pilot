"""Deterministic metric calculations. All arithmetic is Decimal; SQL only filters and selects versions.

Selection order for an observation: latest revision known at the data cutoff per (source, record) ->
eligibility (approval, scope, currency, basis, effective interval) -> latest as_of on/before the date -> age check.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D
from typing import Optional

from .config import ClientConfig
from .taxonomy import select_funds
from .windows import Window, previous_period_start

ZERO = D(0)


@dataclass
class Sel:
    state: str                      # available | missing | stale | unapproved | incompatible_*
    obs: Optional[sqlite3.Row] = None

    @property
    def usable(self) -> bool:
        return self.state == "available"

    @property
    def value(self) -> Optional[D]:
        return D(self.obs["value"]) if self.obs is not None else None

    @property
    def as_of(self) -> Optional[date]:
        return date.fromisoformat(self.obs["as_of_date"]) if self.obs is not None else None


def select_observation(conn, cfg: ClientConfig, fund_id: str, metric: str, on_or_before: date, cutoff: str) -> Sel:
    rows = conn.execute(
        """SELECT m.* FROM metric_observations m JOIN sources s ON m.source_id=s.source_id
           WHERE m.fund_id=? AND m.metric_name=? AND m.first_observed_at<=?
             AND s.internal_report_allowed=1 AND (m.available_at IS NULL OR m.available_at<=?)""",
        (fund_id, metric, cutoff, cutoff[:10])).fetchall()
    latest: dict[tuple, sqlite3.Row] = {}
    for r in rows:
        k = (r["source_id"], r["external_record_id"])
        if k not in latest or r["revision"] > latest[k]["revision"]:
            latest[k] = r
    is_fee = metric.startswith("expense_ratio") or metric == "management_fee"
    ok: list[sqlite3.Row] = []
    first_reason: Optional[str] = None
    for r in latest.values():
        if r["as_of_date"] > on_or_before.isoformat():
            continue
        reason = None
        if r["review_status"] != "approved":
            reason = "unapproved"
        elif r["scope"] != "product":
            reason = "incompatible_scope"
        elif not is_fee and r["currency"] != cfg.report_currency:
            reason = "incompatible_currency"
        elif metric == "net_assets" and r["asset_basis"] != "net":
            reason = "incompatible_basis"
        elif is_fee and ((r["effective_from"] and r["effective_from"] > on_or_before.isoformat())
                         or (r["effective_to"] and r["effective_to"] < on_or_before.isoformat())):
            reason = "outside_effective_interval"
        if reason:
            first_reason = first_reason or reason
        else:
            ok.append(r)
    if not ok:
        return Sel(first_reason or "missing")
    best = max(ok, key=lambda r: (r["as_of_date"], r["first_observed_at"]))
    age = (on_or_before - date.fromisoformat(best["as_of_date"])).days
    limit = cfg.max_fee_age_days if is_fee else cfg.max_asset_age_days
    return Sel("stale" if age > limit else "available", best)


def pct_change(base: D, cur: D) -> Optional[D]:
    return None if base == 0 else (cur - base) * 100 / base


def compute_revenue(conn, cfg: ClientConfig, window: Window, cutoff: str, fund_ids: set[str]) -> dict:
    """Use reported product revenue for exact, comparable periods."""
    previous = previous_period_start(window)
    boundary = (window.start_local.isoformat(), window.end_local.isoformat())
    baseline_boundary = (previous.isoformat(), boundary[0]) if previous else None
    latest = {}
    for row in conn.execute(
        """SELECT m.* FROM metric_observations m JOIN sources s ON m.source_id=s.source_id
           WHERE m.metric_name='actual_revenue' AND m.first_observed_at<=? AND s.internal_report_allowed=1
             AND (m.available_at IS NULL OR m.available_at<=?) ORDER BY m.revision""",
        (cutoff, cutoff[:10]),
    ):
        if row["fund_id"] in fund_ids:
            latest[(row["source_id"], row["external_record_id"])] = row

    def period_data(period):
        records = {}
        if period:
            for row in latest.values():
                if (row["period_start"], row["period_end"]) != period or row["review_status"] != "approved":
                    continue
                if row["scope"] == "product" and row["currency"] == cfg.report_currency and row["unit"] == "currency_units":
                    records.setdefault(row["fund_id"], []).append(row)
        return {
            fid: max(rows, key=lambda row: (row["first_observed_at"], row["obs_id"]))
            for fid, rows in records.items() if len({D(row["value"]) for row in rows}) == 1
        }

    current = period_data(boundary)
    baseline = period_data(baseline_boundary)
    common = current.keys() & baseline.keys()
    current_total = sum((D(row["value"]) for row in current.values()), ZERO) if current else None
    matched_current = sum((D(current[fid]["value"]) for fid in common), ZERO) if common else None
    matched_baseline = sum((D(baseline[fid]["value"]) for fid in common), ZERO) if common else None
    return {
        "current": current_total, "coverage": len(current), "matched_size": len(common),
        "matched_current": matched_current, "matched_baseline": matched_baseline,
        "change": matched_current - matched_baseline if common else None,
        "pct": pct_change(matched_baseline, matched_current) if common else None,
        "period": boundary, "baseline_period": baseline_boundary,
        "obs_ids": {row["obs_id"] for row in [*baseline.values(), *current.values()]},
    }


def active_on(f: sqlite3.Row, d: date) -> bool:
    if not f["launch_date"]:
        return False
    if date.fromisoformat(f["launch_date"]) > d:
        return False
    return not (f["closure_date"] and d >= date.fromisoformat(f["closure_date"]))


def _common_date(sels: list[Sel]) -> tuple[Optional[date], bool]:
    dates = {s.as_of for s in sels}
    return (next(iter(dates)) if len(dates) == 1 else None), len(dates) <= 1


def _total(sels: dict[str, Sel], require_common: bool) -> dict:
    usable = {k: s for k, s in sels.items() if s.usable}
    if not usable:
        return {"state": "unavailable", "total": None, "as_of": None, "n": 0, "obs_ids": []}
    as_of, common = _common_date(list(usable.values()))
    if require_common and not common:
        return {"state": "unavailable_common_date", "total": None, "as_of": None, "n": len(usable),
                "obs_ids": [s.obs["obs_id"] for s in usable.values()],
                "as_of_range": (min(s.as_of for s in usable.values()), max(s.as_of for s in usable.values()))}
    return {"state": "available", "total": sum((s.value for s in usable.values()), ZERO), "as_of": as_of,
            "n": len(usable), "obs_ids": [s.obs["obs_id"] for s in usable.values()]}


def compute_metrics(conn, cfg: ClientConfig, window: Window, cutoff: str, *, funds=None) -> dict:
    if funds is None:
        funds = select_funds(conn, cfg)
    base_d, cur_d = window.baseline_date, window.current_date
    unknown_lifecycle = [f["fund_id"] for f in funds if not f["launch_date"]]
    act_b = [f for f in funds if active_on(f, base_d)]
    act_c = [f for f in funds if active_on(f, cur_d)]
    ids_b, ids_c = {f["fund_id"] for f in act_b}, {f["fund_id"] for f in act_c}
    by_id = {f["fund_id"]: f for f in funds}

    counts = {
        "baseline": len(ids_b), "current": len(ids_c), "change": len(ids_c) - len(ids_b),
        "launched": sorted(ids_c - ids_b), "closed": sorted(ids_b - ids_c),
        "proxy_baseline": sum(1 for i in ids_b if by_id[i]["launch_date_basis"] == "inception_proxy"),
        "proxy_current": sum(1 for i in ids_c if by_id[i]["launch_date_basis"] == "inception_proxy"),
        "unknown_lifecycle": unknown_lifecycle,
    }

    rows, a_b, a_c = {}, {}, {}
    for f in funds:
        fid = f["fund_id"]
        if fid not in ids_b and fid not in ids_c:
            continue
        sb = select_observation(conn, cfg, fid, "net_assets", base_d, cutoff) if fid in ids_b else Sel("not_active")
        sc = select_observation(conn, cfg, fid, "net_assets", cur_d, cutoff) if fid in ids_c else Sel("not_active")
        a_b[fid], a_c[fid] = sb, sc
        fb = select_observation(conn, cfg, fid, cfg.primary_fee_metric, base_d, cutoff) if fid in ids_b else Sel("not_active")
        fc = select_observation(conn, cfg, fid, cfg.primary_fee_metric, cur_d, cutoff) if fid in ids_c else Sel("not_active")
        # fee only pairs with assets when dates are within the configured gap
        for fs, asel in ((fb, sb), (fc, sc)):
            if fs.usable and asel.usable and abs((fs.as_of - asel.as_of).days) > cfg.max_fee_asset_date_gap_days:
                fs.state = "fee_asset_date_gap"
        rows[fid] = {"fund": f, "assets_baseline": sb, "assets_current": sc, "fee_baseline": fb, "fee_current": fc}

    def label(s: Sel, side: str) -> str:
        return {"missing": f"unavailable_{side}", "not_active": "not_active"}.get(s.state, s.state)

    snap_b = _total(a_b, cfg.require_same_group_as_of_date)
    snap_c = _total(a_c, cfg.require_same_group_as_of_date)
    snap_c["coverage"] = (snap_c["n"], len(ids_c))
    snap_b["coverage"] = (snap_b["n"], len(ids_b))

    cohort = [i for i in rows if i in ids_b and i in ids_c and a_b[i].usable and a_c[i].usable]
    mb = _total({i: a_b[i] for i in cohort}, cfg.require_same_group_as_of_date)
    mc = _total({i: a_c[i] for i in cohort}, cfg.require_same_group_as_of_date)
    matched = {"cohort": cohort, "baseline": mb, "current": mc, "coverage": (len(cohort), len(ids_c)),
               "absolute_change": None, "percent_change": None, "state": "available"}
    if mb["state"] == "available" and mc["state"] == "available":
        matched["absolute_change"] = mc["total"] - mb["total"]
        matched["percent_change"] = pct_change(mb["total"], mc["total"])
    else:
        matched["state"] = "unavailable_common_date" if "unavailable_common_date" in (mb["state"], mc["state"]) else "unavailable"

    fee_rows = []
    for i, r in rows.items():
        entry = {"fund_id": i, "baseline": r["fee_baseline"], "current": r["fee_current"], "bps_change": None}
        if r["fee_baseline"].usable and r["fee_current"].usable:
            entry["bps_change"] = (r["fee_current"].value - r["fee_baseline"].value) * 10000
        fee_rows.append(entry)

    fee_cohort = [i for i in cohort if rows[i]["fee_baseline"].usable and rows[i]["fee_current"].usable]
    weighted = {"state": "unavailable", "fee_cohort": fee_cohort, "coverage_products": (len(fee_cohort), len(cohort)),
                "coverage_asset_weight": None}
    proxy_allowed = cfg.allow_revenue_proxy and cfg.primary_fee_metric == "expense_ratio_net"
    proxy = {"state": "unavailable" if proxy_allowed else "unavailable_disabled"}
    shared_asset_dates = all(_common_date([assets[i] for i in fee_cohort])[1] for assets in (a_b, a_c))
    if cfg.require_same_group_as_of_date and not shared_asset_dates:
        weighted["state"] = "unavailable_common_date"
        if proxy_allowed:
            proxy["state"] = "unavailable_common_date"
    elif fee_cohort:
        wb = sum((a_b[i].value for i in fee_cohort), ZERO)
        wc = sum((a_c[i].value for i in fee_cohort), ZERO)
        if wb > 0 and wc > 0 and cohort:
            fb = sum((a_b[i].value * rows[i]["fee_baseline"].value for i in fee_cohort), ZERO) / wb
            fc = sum((a_c[i].value * rows[i]["fee_current"].value for i in fee_cohort), ZERO) / wc
            fee_effect = sum(((a_b[i].value / wb) * (rows[i]["fee_current"].value - rows[i]["fee_baseline"].value)
                              for i in fee_cohort), ZERO) * 10000
            total_bps = (fc - fb) * 10000
            cohort_base = mb["total"]
            weighted.update({"state": "available", "baseline": fb, "current": fc, "change_bps": total_bps,
                             "product_fee_effect_bps": fee_effect, "composition_effect_bps": total_bps - fee_effect,
                             "coverage_asset_weight": (wb / cohort_base * 100) if cohort_base else None})
        if proxy_allowed:
            pb = sum((a_b[i].value * rows[i]["fee_baseline"].value for i in fee_cohort), ZERO)
            pc = sum((a_c[i].value * rows[i]["fee_current"].value for i in fee_cohort), ZERO)
            proxy = {"state": "available", "baseline": pb, "current": pc, "absolute_change": pc - pb,
                     "percent_change": pct_change(pb, pc), "n": len(fee_cohort)}

    per_product = []
    for i, r in rows.items():
        sb, sc = r["assets_baseline"], r["assets_current"]
        ch = pc = None
        if sb.usable and sc.usable:
            ch, pc = sc.value - sb.value, pct_change(sb.value, sc.value)
        per_product.append({"fund_id": i, "ticker": r["fund"]["ticker"], "name": r["fund"]["name"],
                            "assets_baseline": sb, "assets_current": sc,
                            "assets_baseline_state": "available" if sb.usable else label(sb, "baseline"),
                            "assets_current_state": "available" if sc.usable else label(sc, "current"),
                            "absolute_change": ch, "percent_change": pc,
                            "in_matched_cohort": i in cohort})
    return {"baseline_date": base_d, "current_date": cur_d, "counts": counts, "snapshot_baseline": snap_b,
            "snapshot_current": snap_c, "matched": matched, "per_product": per_product, "fees": fee_rows,
            "weighted_fee": weighted, "proxy": proxy, "universe_size": len(funds)}
