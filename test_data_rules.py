import json
from datetime import date
from decimal import Decimal as D

import pytest

from conftest import METRIC_HDR, NEWS_HDR, PRODUCT_HDR, metric_row, prod_row, write
from etf_pilot.importers import import_metrics, import_news, import_products
from etf_pilot.metrics import compute_metrics, select_observation
from etf_pilot.windows import make_window

CUT = "2026-10-08T12:00:00Z"
OBS = "2026-10-07T18:00:00Z"


def window(cfg):
    return make_window("weekly", date(2026, 10, 8), cfg.report_timezone)


def seed(cfg, conn, tmp_path, products, metrics):
    import_products(conn, cfg, write(tmp_path, "p.csv", PRODUCT_HDR + products))
    return import_metrics(conn, cfg, write(tmp_path, "m.csv", METRIC_HDR + metrics), OBS)


def test_rerun_import_has_no_duplicates(cfg, conn, tmp_path):
    rows = metric_row("a1", "alpha", "net_assets", "1", "currency_units", "2026-09-30")
    seed(cfg, conn, tmp_path, prod_row("alpha", "ALFA"), rows)
    again = import_metrics(conn, cfg, tmp_path / "m.csv", OBS)
    assert (again.inserted, again.skipped, again.rejected) == (0, 1, 0)
    assert conn.execute("SELECT COUNT(*) FROM metric_observations").fetchone()[0] == 1


def test_amendment_selected_once_original_retained_and_cutoff_respected(cfg, conn, tmp_path):
    rows = metric_row("g1", "g", "net_assets", "5000000", "currency_units", "2026-10-07")
    seed(cfg, conn, tmp_path, prod_row("g", "GAMA"), rows)
    res = import_metrics(conn, cfg, write(tmp_path, "amend.csv", METRIC_HDR + metric_row("g1", "g", "net_assets", "5500000", "currency_units", "2026-10-07", rev=2)), "2026-10-08T01:00:00Z")
    assert res.inserted == 1
    assert conn.execute("SELECT COUNT(*) FROM metric_observations").fetchone()[0] == 2  # original retained
    d = date(2026, 10, 7)
    assert select_observation(conn, cfg, "g", "net_assets", d, CUT).value == D("5500000")
    assert select_observation(conn, cfg, "g", "net_assets", d, "2026-10-07T20:00:00Z").value == D("5000000")  # frozen report unchanged


def test_conflicting_revision_is_rejected_not_overwritten(cfg, conn, tmp_path):
    seed(cfg, conn, tmp_path, prod_row("g", "GAMA"), metric_row("g1", "g", "net_assets", "5", "currency_units", "2026-10-07"))
    bad = write(tmp_path, "c.csv", METRIC_HDR + metric_row("g1", "g", "net_assets", "6", "currency_units", "2026-10-07"))
    res = import_metrics(conn, cfg, bad, OBS)
    assert res.rejected == 1 and "new, higher revision" in res.errors[0]["suggestion"]


def test_missing_baseline_is_unavailable_not_zero(cfg, conn, tmp_path):
    seed(cfg, conn, tmp_path, prod_row("e", "ECHO"), metric_row("e1", "e", "net_assets", "20", "currency_units", "2026-10-07"))
    m = compute_metrics(conn, cfg, window(cfg), CUT)
    row = m["per_product"][0]
    assert row["assets_baseline_state"] == "unavailable_baseline"
    assert row["absolute_change"] is None and row["percent_change"] is None
    assert m["matched"]["cohort"] == []


def test_empty_is_unknown_zero_is_kept(cfg, conn, tmp_path):
    rows = metric_row("z1", "z", "net_assets", "", "currency_units", "2026-09-30") + metric_row("z2", "z", "net_assets", "0", "currency_units", "2026-10-07")
    res = seed(cfg, conn, tmp_path, prod_row("z", "ZERO"), rows)
    assert res.rejected == 1 and res.inserted == 1
    assert "empty value means unknown" in res.errors[0]["message"]
    assert select_observation(conn, cfg, "z", "net_assets", date(2026, 10, 7), CUT).value == D("0")


@pytest.mark.parametrize("value,unit", [("0.25", "percent"), ("25", "basis_points"), ("0.0025", "annual_decimal")])
def test_fee_units_normalize_identically(cfg, conn, tmp_path, value, unit):
    seed(cfg, conn, tmp_path, prod_row("f", "FEEE"), metric_row("f1", "f", "expense_ratio_net", value, unit, "2026-10-07"))
    assert select_observation(conn, cfg, "f", "expense_ratio_net", date(2026, 10, 7), CUT).value == D("0.0025")


def test_fee_without_unit_is_rejected_not_guessed(cfg, conn, tmp_path):
    res = seed(cfg, conn, tmp_path, prod_row("f", "FEEE"), metric_row("f1", "f", "expense_ratio_net", "0.25", "", "2026-10-07"))
    assert res.rejected == 1 and res.errors[0]["field"] == "unit"
    assert res.errors[0]["row"] == 2 and res.errors[0]["file"] == "m.csv"


def test_gross_total_assets_never_enters_net_assets(cfg, conn, tmp_path):
    rows = (metric_row("t1", "t", "total_assets", "9", "currency_units", "2026-10-07", basis="gross")
            + metric_row("t2", "t", "net_assets", "8", "currency_units", "2026-10-07", basis="gross"))
    seed(cfg, conn, tmp_path, prod_row("t", "TOTL"), rows)
    s = select_observation(conn, cfg, "t", "net_assets", date(2026, 10, 7), CUT)
    assert not s.usable and s.state == "incompatible_basis"


def test_series_scope_currency_and_unapproved_excluded(cfg, conn, tmp_path):
    rows = (metric_row("s1", "s", "net_assets", "9", "currency_units", "2026-10-07", scope="series")
            + metric_row("s2", "s", "net_assets", "9", "currency_units", "2026-10-06", currency="EUR")
            + metric_row("s3", "s", "net_assets", "9", "currency_units", "2026-10-05", status="pending"))
    seed(cfg, conn, tmp_path, prod_row("s", "SERI"), rows)
    assert not select_observation(conn, cfg, "s", "net_assets", date(2026, 10, 7), CUT).usable


def test_stale_observation_is_flagged_not_forward_filled(cfg, conn, tmp_path):
    seed(cfg, conn, tmp_path, prod_row("o", "OLDD"), metric_row("o1", "o", "net_assets", "9", "currency_units", "2026-01-01"))
    s = select_observation(conn, cfg, "o", "net_assets", date(2026, 10, 7), CUT)
    assert s.state == "stale" and not s.usable


def test_fee_must_be_effective_at_measurement_date(cfg, conn, tmp_path):
    rows = metric_row("f1", "f", "expense_ratio_net", "20", "basis_points", "2026-10-07", eff_from="2026-10-05")
    seed(cfg, conn, tmp_path, prod_row("f", "FEEE"), rows)
    assert not select_observation(conn, cfg, "f", "expense_ratio_net", date(2026, 10, 1), CUT).usable
    assert select_observation(conn, cfg, "f", "expense_ratio_net", date(2026, 10, 7), CUT).usable


def test_mixed_as_of_dates_make_group_total_unavailable(cfg, conn, tmp_path):
    rows = (metric_row("a", "x", "net_assets", "10", "currency_units", "2026-10-06")
            + metric_row("b", "y", "net_assets", "10", "currency_units", "2026-10-07"))
    seed(cfg, conn, tmp_path, prod_row("x", "XXXX") + prod_row("y", "YYYY"), rows)
    m = compute_metrics(conn, cfg, window(cfg), CUT)
    assert m["snapshot_current"]["state"] == "unavailable_common_date"
    assert m["snapshot_current"]["total"] is None


def test_announced_future_launch_does_not_change_count(cfg, conn, tmp_path):
    import_products(conn, cfg, write(tmp_path, "p.csv", PRODUCT_HDR + prod_row("old", "OLDD") + prod_row("fut", "FUTR", launch="2026-12-01")))
    m = compute_metrics(conn, cfg, window(cfg), CUT)
    assert m["counts"]["current"] == 1 and m["counts"]["launched"] == []


def test_one_launch_one_closure_keeps_count_but_shows_both(cfg, conn, tmp_path):
    prods = prod_row("a", "AAAA", closure="2026-10-03") + prod_row("b", "BBBB") + prod_row("c", "CCCC", launch="2026-10-02")
    import_products(conn, cfg, write(tmp_path, "p.csv", PRODUCT_HDR + prods))
    c = compute_metrics(conn, cfg, window(cfg), CUT)["counts"]
    assert c["baseline"] == c["current"] == 2 and c["launched"] == ["c"] and c["closed"] == ["a"]


def test_rejected_product_rows_are_staged_with_location(cfg, conn, tmp_path):
    bad = PRODUCT_HDR + prod_row("ok", "OKOK") + prod_row("bad", "BADD", launch="2020/01/01")
    res = import_products(conn, cfg, write(tmp_path, "p.csv", bad))
    assert res.inserted == 1 and res.rejected == 1
    row = conn.execute("SELECT file,row_number,field FROM rejected_rows").fetchone()
    assert tuple(row) == ("p.csv", 3, "inception_date")


def test_identifiers_keep_leading_zeros(cfg, conn, tmp_path):
    line = "z,Z ETF,ZZZZ,V,US,ETF,demo_capital,USD,0001234567,S000012345,C000012345,2020-01-01,2020-01-01,actual,,,approved\n"
    import_products(conn, cfg, write(tmp_path, "p.csv", PRODUCT_HDR + line))
    assert conn.execute("SELECT value FROM fund_identifiers WHERE id_type='cik'").fetchone()[0] == "0001234567"


NEWS = ("n1,demo_news_import,{t},{u},{p},date,{b},ref,full,false\n")


def news_file(tmp_path, name, *rows):
    return write(tmp_path, name, NEWS_HDR + "".join(rows))


def test_news_dedup_syndication_revision_and_no_extra_launch(cfg, conn, tmp_path):
    import_products(conn, cfg, write(tmp_path, "p.csv", PRODUCT_HDR + prod_row("g", "GAMA", launch="2026-10-02")))
    a = NEWS.format(t="Demo launches GAMA", u="https://x.test/a?utm_source=rss", p="2026-10-01", b="GAMA launched.")
    syn = "n1s,demo_syndicator,Demo launches GAMA,https://x.test/a/,2026-10-01,date,GAMA launched.,ref,full,false\n"
    r = import_news(conn, cfg, news_file(tmp_path, "n.csv", a, syn), OBS)
    assert (r.inserted, r.skipped) == (1, 1)
    assert conn.execute("SELECT COUNT(*) FROM evidence_associations").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    # same record, edited text: new revision, but not a second launch event
    edited = NEWS.format(t="Demo launches GAMA", u="https://x.test/a", p="2026-10-01", b="GAMA launched today (correction).")
    r2 = import_news(conn, cfg, news_file(tmp_path, "n2.csv", edited), "2026-10-09T00:00:00Z")
    assert r2.inserted == 1
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 2
    assert conn.execute("SELECT MAX(revision) FROM evidence").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_earnings_headline_creates_no_event_or_metric(cfg, conn, tmp_path):
    n = NEWS.format(t="Demo Capital reports quarterly earnings", u="https://x.test/e", p="2026-10-06", b="Revenue rose.")
    import_news(conn, cfg, news_file(tmp_path, "n.csv", n), OBS)
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM metric_observations").fetchone()[0] == 0


def test_ambiguous_ticker_is_queued_and_needs_explicit_resolution(cfg, conn, tmp_path):
    from etf_pilot.review import decide

    import_products(conn, cfg, write(tmp_path, "p.csv", PRODUCT_HDR + prod_row("e1", "ECHO", venue="A") + prod_row("e2", "ECHO", venue="B")))
    n = NEWS.format(t="Demo Capital to liquidate ECHO", u="https://x.test/l", p="2026-09-26", b="Details pending.")
    import_news(conn, cfg, news_file(tmp_path, "n.csv", n), OBS)
    ev = conn.execute("SELECT * FROM events").fetchone()
    assert ev["review_status"] == "needs_review" and ev["fund_id"] is None
    assert json.loads(ev["candidate_fund_ids"]) == ["e1", "e2"]
    with pytest.raises(ValueError, match="ambiguous"):
        decide(conn, ev["event_id"], "accept", "reviewer1")
    decide(conn, ev["event_id"], "accept", "reviewer1", reason="venue A confirmed", fund_id="e1", effective_date="2026-10-30")
    ev = conn.execute("SELECT * FROM events").fetchone()
    assert (ev["review_status"], ev["fund_id"], ev["effective_date"]) == ("accepted", "e1", "2026-10-30")
    audit = conn.execute("SELECT reviewer,decision FROM review_actions WHERE entity_type='event'").fetchone()
    assert tuple(audit) == ("reviewer1", "accept")


def test_metadata_only_source_never_retains_body(cfg, conn, tmp_path):
    conn.execute("UPDATE sources SET retention_mode='metadata_only' WHERE source_id='demo_news_import'")
    conn.commit()
    n = NEWS.format(t="Demo launches NEWF", u="https://x.test/m", p="2026-10-06", b="SECRET BODY")
    import_news(conn, cfg, news_file(tmp_path, "n.csv", n), OBS)
    assert conn.execute("SELECT body FROM evidence").fetchone()[0] is None
