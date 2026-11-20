from datetime import date
from pathlib import Path

import pytest

from etf_pilot.config import ConfigError, load_config
from etf_pilot.service import DEMO_CUTOFF, run_demo
from etf_pilot.windows import make_window, subtract_months

ROOT = Path(__file__).resolve().parents[1]


def test_weekly_window_boundaries_in_utc():
    w = make_window("weekly", date(2026, 10, 8), "America/Chicago")
    assert w.start_utc.isoformat() == "2026-10-01T05:00:00+00:00"
    assert w.end_utc.isoformat() == "2026-10-08T05:00:00+00:00"
    assert (w.baseline_date, w.current_date) == (date(2026, 9, 30), date(2026, 10, 7))
    assert w.contains_utc("2026-10-01T05:00:00Z") and not w.contains_utc("2026-10-08T05:00:00Z")


def test_dst_fall_back_window_is_169_hours():
    w = make_window("weekly", date(2026, 11, 2), "America/Chicago")  # DST ends 2026-11-01
    assert (w.end_utc - w.start_utc).total_seconds() == 169 * 3600


def test_month_end_and_leap_year():
    assert subtract_months(date(2027, 3, 31), 1) == date(2027, 2, 28)
    assert subtract_months(date(2028, 3, 31), 1) == date(2028, 2, 29)
    assert subtract_months(date(2028, 2, 29), 12) == date(2027, 2, 28)
    assert make_window("quarterly", date(2026, 10, 1), "UTC").start_local == date(2026, 7, 1)
    assert make_window("10_year", date(2026, 10, 8), "UTC").start_local == date(2016, 10, 8)


def test_unavailable_lookbacks_fail_loudly():
    with pytest.raises(NotImplementedError):
        make_window("last_run", date(2026, 10, 8), "UTC")
    with pytest.raises(ValueError):
        make_window("custom", date(2026, 10, 8), "UTC")


def test_config_rejects_unknown_keys_and_unsafe_modes(tmp_path):
    import yaml
    base = yaml.safe_load((ROOT / "configs" / "demo.yaml").read_text())

    def attempt(**changes):
        d = {**base, **changes}
        p = tmp_path / "c.yaml"
        p.write_text(yaml.safe_dump(d))
        return load_config(str(p), root=tmp_path)

    with pytest.raises(ConfigError, match="bogus"):
        attempt(bogus=1)
    with pytest.raises(ConfigError, match="demo"):
        attempt(database_path="data/pilot/real.sqlite3")
    with pytest.raises(ConfigError, match="forward_fill"):
        attempt(allow_automatic_daily_forward_fill=True)
    with pytest.raises(ConfigError, match="local endpoint"):
        attempt(ai={**base["ai"], "base_url": "https://api.hosted.example"})
    with pytest.raises(ConfigError, match="report_timezone|primary_fee_metric"):
        attempt(primary_fee_metric="revenue")


def test_pilot_config_is_isolated_and_has_no_enabled_sources():
    cfg = load_config("pilot_client", root=ROOT)
    assert "demo" not in cfg.database_path and not any(s.enabled for s in cfg.sources)


def test_observed_at_override_forbidden_outside_demo():
    from etf_pilot.service import check_observed_override
    pilot = load_config("pilot_client", root=ROOT)
    with pytest.raises(ValueError):
        check_observed_override(pilot, "2020-01-01T00:00:00Z")


def test_full_demo_is_reproducible_and_idempotent(tmp_path):
    cfg = load_config(str(ROOT / "configs" / "demo.yaml"), root=tmp_path)
    first = run_demo(cfg, root=ROOT)
    md1 = first["report"]["markdown"].read_text()
    counts1 = [tuple(first["conn"].execute(f"SELECT COUNT(*) FROM {t}").fetchone())[0] for t in ("evidence", "events", "metric_observations", "funds")]
    second = run_demo(cfg, root=ROOT)
    counts2 = [tuple(second["conn"].execute(f"SELECT COUNT(*) FROM {t}").fetchone())[0] for t in ("evidence", "events", "metric_observations", "funds")]
    assert counts1 == counts2 == [4, 3, 13, 5]
    assert all(r.inserted == 0 for r in second["imports"])
    assert second["report"]["markdown"].read_text() == md1
    assert second["report"]["report_id"] == first["report"]["report_id"]
    assert "USD 165,000,000" in md1 and "-5.0 bp" in md1 and "(late arrival)" in md1
    assert "ECHO [demo_echo_a]" in md1  # shared tickers are disambiguated
    assert "needs review" in md1 and "Annualized expense-based proxy" in md1
    assert "DEMO - synthetic data" in md1 and "realized revenue" in md1
    # amendment (5.5M) used at the demo cutoff; original retained
    assert "USD 5,500,000" in md1
    assert first["conn"].execute("SELECT COUNT(*) FROM metric_observations WHERE external_record_id='m_gama_na_1007'").fetchone()[0] == 2


def test_html_escapes_untrusted_text_and_blocks_unsafe_links(tmp_path):
    from etf_pilot.reports import render
    import json
    cfg = load_config(str(ROOT / "configs" / "demo.yaml"), root=tmp_path)
    out = run_demo(cfg, root=ROOT)
    ctx = out["report"]["context"]
    ctx["register"].append({"id": "ev_x", "kind": "news", "source": "s", "title": "<script>alert(1)</script>", "url": None,
                            "date": "2026-10-01", "first_observed": "t", "note": "n"})
    md, html = render(ctx)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    from etf_pilot.reports import _safe_url
    assert _safe_url("javascript:alert(1)") is None and _safe_url("https://a.test/x") == "https://a.test/x"


def test_manifest_lists_ids_and_versions(tmp_path):
    import json
    cfg = load_config(str(ROOT / "configs" / "demo.yaml"), root=tmp_path)
    m = json.loads(run_demo(cfg, root=ROOT)["report"]["manifest"].read_text())
    assert m["data_cutoff"] == DEMO_CUTOFF and m["mode"] == "retrospective"
    assert len(m["observation_ids"]) >= 8 and len(m["evidence_ids"]) == 3 and m["method_versions"]["metrics"]
