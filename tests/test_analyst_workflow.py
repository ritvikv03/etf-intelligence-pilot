import json
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from conftest import METRIC_HDR, NEWS_HDR, ROOT, write
from etf_pilot.artifacts import change_report_status, export_saved_report, read_artifacts
from etf_pilot.config import SourceConfig
from etf_pilot.db import run_lock, sync_sources
from etf_pilot.feeds import collect_feeds, parse_feed
from etf_pilot.importers import import_metrics, import_news
from etf_pilot.reports import generate_report
from etf_pilot.service import DEMO_CUTOFF, DEMO_END, run_demo
from etf_pilot.synthesis import PROMPT_VERSION, add_local_synthesis, evaluate_local_model
from etf_pilot.taxonomy import product_tags, review_tags

RSS = b"""<rss version="2.0"><channel><item><guid>stable-1</guid>
<title>New strategy commentary</title><link>https://stories.example.test/one</link>
<pubDate>Wed, 07 Oct 2026 09:00:00 GMT</pubDate>
<description>Sample archive text</description></item></channel></rss>"""


def feed(source_id):
    return SourceConfig(
        source_id=source_id, source_type="rss", enabled=True, owner="Test analyst", purpose="news",
        endpoint="https://" + source_id + ".example.test/feed", permission_status="synthetic_fixture",
        permission_reference="Local test fixture", retention_mode="metadata_only", internal_report_allowed=True,
    )


def test_feed_failure_isolated_and_cursor_advances_only_after_import(cfg, conn):
    cfg.sources.extend([feed("news_feed"), feed("broken_feed")])
    sync_sources(conn, cfg)

    def fetch(url, validators):
        if "broken_feed" in url:
            return b"<rss", {"ETag": "broken"}
        assert not validators
        return RSS, {"ETag": "first"}

    results = collect_feeds(conn, cfg, fetch=fetch)
    assert [r["status"] for r in results] == ["success", "failed"]
    assert [tuple(r) for r in conn.execute("SELECT source_id,etag FROM feed_cursors")] == [("news_feed", "first")]
    assert conn.execute("SELECT body FROM evidence").fetchone()[0] is None

    def repeat(url, validators):
        assert validators == {"If-None-Match": "first"}
        return None, {}

    assert collect_feeds(conn, cfg, "news_feed", fetch=repeat)[0]["status"] == "unchanged"

    def amendment(url, validators):
        assert validators == {"If-None-Match": "first"}
        return RSS.replace(b"Sample archive text", b"Revised archive text"), {"ETag": "second"}

    assert collect_feeds(conn, cfg, "news_feed", fetch=amendment)[0]["inserted"] == 1
    assert conn.execute("SELECT max(revision) FROM evidence").fetchone()[0] == 2
    assert conn.execute("SELECT etag FROM feed_cursors").fetchone()[0] == "second"
    with run_lock(cfg.db_file, "collection"):
        with pytest.raises(ValueError, match="already in progress"):
            collect_feeds(conn, cfg, "news_feed", fetch=repeat)


def test_atom_keeps_an_update_timestamp_separate_from_publication():
    source = feed("atom_feed")
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <id>record</id><title>Test item</title><link href="https://news.example.test/item"/>
    <updated>2026-10-07T10:00:00Z</updated></entry></feed>"""
    row, = parse_feed(atom, str(source.endpoint), source)
    assert row["external_record_id"] == "record" and row["date_precision"] == "unknown"
    with pytest.raises(ValueError, match="XML declarations"):
        parse_feed(b'<!DOCTYPE rss [<!ENTITY bad "x">]><rss/>', str(source.endpoint), source)


def test_composite_taxonomy_rolls_up_and_reviewed_tags_survive_demo(cfg):
    out = run_demo(cfg, ROOT)
    with closing(out["conn"]) as conn:
        brief = generate_report(conn, cfg, "weekly", DEMO_END, DEMO_CUTOFF,
                                tag_ids=["equity", "small_cap", "us_exposure"])
        assert list(brief["context"]["selected_products"]) == ["demo_alpha"]
        assert brief["context"]["counts"]["current"] == 1
        review_tags(conn, cfg, "demo_alpha", ["small_cap", "international_exposure"], "Research reviewer")
    again = run_demo(cfg, ROOT)
    with closing(again["conn"]) as conn:
        assert product_tags(conn)["demo_alpha"] == {"small_cap", "international_exposure"}
        filtered = generate_report(conn, cfg, "weekly", DEMO_END, DEMO_CUTOFF, tag_ids=["small_cap", "us_exposure"])
        assert filtered["context"]["counts"]["current"] == 0


def test_last_run_catches_late_arrivals_and_full_history_uses_available_records(cfg, tmp_path):
    out = run_demo(cfg, ROOT)
    with closing(out["conn"]) as conn:
        item = ("late-note,demo_news_import,Demo BETA closes fund,https://example.test/late,"
                "2026-10-01,date,Late coverage,,full,false\n")
        import_news(conn, cfg, write(tmp_path, "late.csv", NEWS_HDR + item), "2026-10-10T12:00:00Z")
        end = date(2026, 10, 15)
        cutoff = "2026-10-15T12:00:00Z"
        result = generate_report(conn, cfg, "last_run", end, cutoff)
        context = result["context"]
        assert context["window"]["start"] == "2026-10-08"
        assert context["manifest"]["observed_after"] == DEMO_CUTOFF
        assert any(e["late"] and "BETA" in e["title"] for e in context["events"])
        assert generate_report(conn, cfg, "last_run", end, cutoff)["report_id"] == result["report_id"]
        history = generate_report(conn, cfg, "full_history", end, cutoff)
        assert history["context"]["window"]["start"] == "2021-05-06"


def test_revenue_uses_reported_values_for_exact_periods(cfg, tmp_path):
    source = cfg.sources[-1].model_copy(update={"source_id": "revenue", "purpose": "actual_revenue"})
    cfg.sources.append(source)
    out = run_demo(cfg, ROOT)
    with closing(out["conn"]) as conn:
        header = METRIC_HDR.strip() + ",period_start,period_end\n"
        records = (
            "rev-prior,demo_alpha,actual_revenue,75,currency_units,USD,product,unknown,"
            "2026-09-30,,,,,revenue,https://example.test/prior,prior stated revenue,1,approved,2026-09-24,2026-10-01\n"
            "rev-now,demo_alpha,actual_revenue,100,currency_units,USD,product,unknown,"
            "2026-10-07,,,,,revenue,https://example.test/now,current stated revenue,1,approved,2026-10-01,2026-10-08\n"
        )
        result = import_metrics(conn, cfg, write(tmp_path, "revenue.csv", header + records), DEMO_CUTOFF)
        assert result.inserted == 2 and result.rejected == 0
        report = generate_report(conn, cfg, "weekly", DEMO_END, DEMO_CUTOFF)
        revenue = report["context"]["revenue"]
        assert (revenue["current"], revenue["matched_baseline"], revenue["change"]) == ("USD 100", "USD 75", "+USD 25")
        different = generate_report(conn, cfg, "monthly", DEMO_END, DEMO_CUTOFF)
        assert different["context"]["revenue"]["current"] == "unavailable"


def test_review_and_finalize_freezes_artifacts(cfg):
    out = run_demo(cfg, ROOT)
    rid = out["report"]["report_id"]
    with closing(out["conn"]) as conn:
        with pytest.raises(ValueError, match="reviewed"):
            change_report_status(conn, cfg, rid, "finalized", "Sam")
        change_report_status(conn, cfg, rid, "reviewed", "Sam")
        change_report_status(conn, cfg, rid, "finalized", "Sam")
        frozen = read_artifacts(conn, rid)
        assert "Status: FINALIZED" in frozen["html"]
        assert json.loads(frozen["manifest"])["finalized"]["by"] == "Sam"
        out["report"]["html"].unlink()
        recovered = export_saved_report(conn, cfg, rid)
        assert recovered["html"].read_text() == frozen["html"]
    again = run_demo(cfg, ROOT)
    with closing(again["conn"]) as conn:
        assert again["report"]["context"]["status"] == "finalized"
        assert read_artifacts(conn, rid) == frozen


def test_failed_export_preserves_report_and_checkpoint(cfg, monkeypatch):
    out = run_demo(cfg, ROOT)
    rid = out["report"]["report_id"]
    with closing(out["conn"]) as conn:
        before = read_artifacts(conn, rid)
        checkpoint = tuple(conn.execute("SELECT * FROM report_checkpoints").fetchone())
        original = Path.replace

        def replace(self, target):
            if self.name == "html" and self.parent.parent == cfg.export_path:
                raise OSError("test export failure")
            return original(self, target)

        monkeypatch.setattr(Path, "replace", replace)
        with pytest.raises(OSError, match="test export failure"):
            generate_report(conn, cfg, "weekly", DEMO_END, DEMO_CUTOFF, profile="demo_weekly")
        assert out["report"]["markdown"].read_text() == before["markdown"]
        assert read_artifacts(conn, rid) == before
        assert tuple(conn.execute("SELECT * FROM report_checkpoints").fetchone()) == checkpoint


def test_model_gate_uses_permitted_evidence_and_falls_back_on_bad_citations(cfg, monkeypatch, tmp_path):
    evaluation = write(tmp_path, "evaluation.json", json.dumps({
        "model": "test-model", "prompt_version": PROMPT_VERSION, "reviewed_by": "Synthetic test evaluator",
        "sample_count": 7, "citation_accuracy": 1, "classification_accuracy": .9, "relevance_accuracy": .9,
        "unsupported_claims": 0, "max_latency_seconds": 1, "cost_per_run": 0,
    }))
    cfg.ai = cfg.ai.model_copy(update={"enabled": True, "evaluation_path": str(evaluation)})
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    out = run_demo(cfg, ROOT)
    context = out["report"]["context"]
    with closing(out["conn"]) as conn:
        with conn:
            conn.execute("UPDATE evidence SET ai_allowed=1")
            conn.execute("UPDATE sources SET ai_allowed=1 WHERE source_id='demo_news_import'")
        def ask(endpoint, model, payload):
            assert endpoint.startswith("http://127.0.0.1")
            cited = payload["evidence"][0]["id"]
            return {"items": [{"pillar": "product_activity", "text": "A launch was proposed.", "evidence_ids": [cited]}]}

        add_local_synthesis(conn, cfg, context, ask=ask)
        assert context["synthesis"]["method"] == "local_model"
        second = generate_report(conn, cfg, "weekly", DEMO_END, DEMO_CUTOFF)["context"]
        add_local_synthesis(conn, cfg, second, ask=lambda *args: {"items": [{
            "pillar": "assets_growth", "text": "A headline for review.", "evidence_ids": ["invented"],
        }]})
        assert second["synthesis"]["method"] == "evidence_extract"
        assert "checks" in second["synthesis"]["notice"]


def test_local_evaluation_scores_cited_labels_without_sending_answers(cfg, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    item = {"pillar": "product_activity", "text": "A launch was proposed.", "evidence_ids": ["ev_test"]}
    suggestion = {"fund_id": "alpha", "tag_id": "small_cap", "evidence_ids": ["ev_test"]}
    case = {
        "payload": {"pillars": ["product_activity"], "funds": {"alpha": "Alpha"},
                    "tags": {"small_cap": "Small cap"}, "evidence": [{"id": "ev_test", "title": "Alpha launch"}]},
        "approved_summaries": [item],
        "expected_tags": [["alpha", "small_cap"]],
    }

    def ask(endpoint, model, payload):
        assert payload == case["payload"]
        return {"items": [item], "tag_suggestions": [suggestion]}

    report = evaluate_local_model(cfg, {
        "reviewed_by": "Synthetic test evaluator", "permission_reference": "Synthetic corpus", "cases": [case] * 5,
    }, ask=ask)
    assert report["sample_count"] == 5
    assert report["classification_accuracy"] == report["citation_accuracy"] == 1
    assert report["unsupported_claims"] == 0
