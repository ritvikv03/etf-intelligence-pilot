"""Section 19.1 deterministic fixture: Alpha/Beta."""
from datetime import date
from decimal import Decimal as D

import pytest

from conftest import METRIC_HDR, PRODUCT_HDR, metric_row, prod_row, write
from etf_pilot.importers import import_metrics, import_products
from etf_pilot.metrics import compute_metrics, pct_change
from etf_pilot.windows import make_window

CUT = "2026-10-08T12:00:00Z"
OBS = "2026-10-07T18:00:00Z"


def build(cfg, conn, tmp_path):
    import_products(conn, cfg, write(tmp_path, "p.csv", PRODUCT_HDR + prod_row("alpha", "ALFA") + prod_row("beta", "BETA")))
    rows = (metric_row("a1", "alpha", "net_assets", "100000000", "currency_units", "2026-09-30")
            + metric_row("b1", "beta", "net_assets", "50000000", "currency_units", "2026-09-30")
            + metric_row("a2", "alpha", "net_assets", "120000000", "currency_units", "2026-10-07")
            + metric_row("b2", "beta", "net_assets", "45000000", "currency_units", "2026-10-07")
            + metric_row("af1", "alpha", "expense_ratio_net", "0.25", "percent", "2026-09-30")
            + metric_row("af2", "alpha", "expense_ratio_net", "20", "basis_points", "2026-10-07")
            + metric_row("bf1", "beta", "expense_ratio_net", "0.0040", "annual_decimal", "2026-09-30")
            + metric_row("bf2", "beta", "expense_ratio_net", "0.40", "percent", "2026-10-07"))
    res = import_metrics(conn, cfg, write(tmp_path, "m.csv", METRIC_HDR + rows), OBS)
    assert res.rejected == 0 and res.inserted == 8
    return compute_metrics(conn, cfg, make_window("weekly", date(2026, 10, 8), cfg.report_timezone), CUT)


def test_matched_cohort_and_fees(cfg, conn, tmp_path):
    m = build(cfg, conn, tmp_path)
    mt = m["matched"]
    assert mt["baseline"]["total"] == D("150000000")
    assert mt["current"]["total"] == D("165000000")
    assert mt["absolute_change"] == D("15000000")
    assert mt["percent_change"] == D("10")
    fees = {f["fund_id"]: f for f in m["fees"]}
    assert fees["alpha"]["bps_change"] == D("-5")
    assert fees["beta"]["bps_change"] == D("0")
    w = m["weighted_fee"]
    assert w["baseline"] == D("0.003")
    assert abs(w["current"] - D("0.00254545454545")) < D("0.0000000001")
    assert abs(w["change_bps"] - (w["product_fee_effect_bps"] + w["composition_effect_bps"])) < D("1e-12")


def test_expense_based_proxy(cfg, conn, tmp_path):
    p = build(cfg, conn, tmp_path)["proxy"]
    assert p["baseline"] == D("450000") and p["current"] == D("420000")
    assert p["absolute_change"] == D("-30000")
    assert abs(p["percent_change"] - D("-6.666666666")) < D("0.0000001")


def test_proxy_disabled_by_config(cfg, conn, tmp_path):
    cfg.allow_revenue_proxy = False
    assert build(cfg, conn, tmp_path)["proxy"]["state"] == "unavailable_disabled"


@pytest.mark.parametrize(
    "metric,label", [("management_fee", "management fee"), ("expense_ratio_gross", "gross expense ratio")]
)
def test_report_labels_selected_fee_and_requires_net_expenses_for_proxy(cfg, conn, tmp_path, metric, label):
    from etf_pilot.reports import generate_report

    build(cfg, conn, tmp_path)
    cfg.primary_fee_metric = metric
    rows = (metric_row("other_fee_b", "alpha", metric, "10", "basis_points", "2026-09-30")
            + metric_row("other_fee_c", "alpha", metric, "15", "basis_points", "2026-10-07"))
    assert import_metrics(conn, cfg, write(tmp_path, "other_fees.csv", METRIC_HDR + rows), OBS).inserted == 2
    report = generate_report(conn, cfg, "weekly", date(2026, 10, 8), CUT)
    for kind in ("markdown", "html"):
        text = report[kind].read_text()
        assert f"Asset-weighted {label}" in text
        assert "Asset-weighted net expense ratio" not in text
        assert "0.1000%" in text and "0.1500%" in text
    assert report["context"]["proxy"]["state"] == "unavailable_disabled"


def test_weighted_fee_and_proxy_require_common_asset_dates(cfg, conn, tmp_path):
    build(cfg, conn, tmp_path)
    rows = metric_row("b2", "beta", "net_assets", "45000000", "currency_units", "2026-10-06", rev=2)
    assert import_metrics(conn, cfg, write(tmp_path, "amend.csv", METRIC_HDR + rows), OBS).inserted == 1
    result = compute_metrics(conn, cfg, make_window("weekly", date(2026, 10, 8), cfg.report_timezone), CUT)
    for name in ("matched", "weighted_fee", "proxy"):
        assert result[name]["state"] == "unavailable_common_date"


def test_report_prints_the_currency_used_to_select_assets(cfg, conn, tmp_path):
    from etf_pilot.reports import generate_report

    cfg.report_currency = "EUR"
    import_products(conn, cfg, write(tmp_path, "p.csv", PRODUCT_HDR + prod_row("alpha", "ALFA")))
    rows = metric_row("asset", "alpha", "net_assets", "200", "currency_units", "2026-10-07", currency="EUR")
    import_metrics(conn, cfg, write(tmp_path, "m.csv", METRIC_HDR + rows), OBS)
    report = generate_report(conn, cfg, "weekly", date(2026, 10, 8), CUT)
    for kind in ("markdown", "html"):
        text = report[kind].read_text()
        assert "EUR 200" in text and "USD 200" not in text
    assert report["context"]["manifest"]["report_currency"] == "EUR"


def test_zero_baseline_percent_is_not_applicable():
    assert pct_change(D(0), D(5)) is None
