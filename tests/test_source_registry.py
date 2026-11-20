import sqlite3
from contextlib import closing

import pytest
import yaml

from conftest import METRIC_HDR, PRODUCT_HDR, ROOT, metric_row, prod_row, write
from etf_pilot.config import ConfigError, load_config
from etf_pilot.db import connect, migrate, source_health, sync_sources
from etf_pilot.importers import import_metrics, import_products

OBSERVED = "2026-10-07T18:00:00Z"


def test_registry_checks_new_roles_and_accepts_existing_configs(tmp_path):
    config = yaml.safe_load((ROOT / "configs" / "demo.yaml").read_text())
    first = config["sources"][0]

    def attempt(sources):
        return load_config(str(write(tmp_path, "client.yaml", yaml.safe_dump({**config, "sources": sources}))), root=tmp_path)

    with pytest.raises(ConfigError, match="duplicate source_id"):
        attempt([first, first])
    with pytest.raises(ConfigError, match="owner is required"):
        attempt([{**first, "owner": None}])
    with pytest.raises(ConfigError, match="endpoint must not contain credentials"):
        attempt([{**first, "endpoint": "https://account:example@data.example.test/"}])

    old_source = {key: value for key, value in first.items() if key not in {"purpose", "owner"}}
    assert attempt([old_source]).sources[0].purpose is None


def test_source_health_attributes_mixed_file_results_and_retries(cfg, conn, tmp_path):
    metrics = next(s for s in cfg.sources if s.source_id == "demo_metrics_import")
    cfg.sources.append(metrics.model_copy(update={"source_id": "demo_revenue", "purpose": "actual_revenue"}))
    sync_sources(conn, cfg)
    import_products(conn, cfg, write(tmp_path, "products.csv", PRODUCT_HDR + prod_row("a", "AAAA")))
    valid = metric_row("assets", "a", "net_assets", "5", "currency_units", "2026-10-07")
    wrong_purpose = valid.replace("demo_metrics_import", "demo_revenue")
    file = write(tmp_path, "metrics.csv", METRIC_HDR + valid + wrong_purpose)
    result = import_metrics(conn, cfg, file, OBSERVED)
    assert (result.inserted, result.rejected) == (1, 1)
    assert "fund_metrics" in result.errors[0]["suggestion"]

    retry = import_metrics(conn, cfg, file, OBSERVED)
    assert (retry.inserted, retry.skipped, retry.rejected) == (0, 1, 1)
    health = {row["source_id"]: dict(row) for row in source_health(conn)}
    assert health["demo_metrics_import"]["status"] == "success"
    assert (health["demo_metrics_import"]["inserted"], health["demo_metrics_import"]["skipped"]) == (0, 1)
    assert health["demo_revenue"]["status"] == "failed" and health["demo_revenue"]["rejected"] == 1
    assert health["demo_news_import"]["status"] == "unrecorded"
    assert conn.execute("SELECT count(*) FROM source_import_runs").fetchone()[0] == 4

    revenue = metric_row("revenue", "a", "actual_revenue", "1", "currency_units", "2026-10-07")
    partial = import_metrics(conn, cfg, write(tmp_path, "partial.csv", METRIC_HDR + valid + revenue), OBSERVED)
    assert (partial.skipped, partial.rejected) == (1, 1)
    assert "actual_revenue" in partial.errors[0]["suggestion"]

    cfg.sources = [s for s in cfg.sources if s.source_id != "demo_metrics_import"]
    sync_sources(conn, cfg)
    health = {row["source_id"]: dict(row) for row in source_health(conn)}
    assert health["demo_metrics_import"]["enabled"] == 0
    assert health["demo_metrics_import"]["status"] == "partial"
    assert conn.execute("SELECT count(*) FROM metric_observations").fetchone()[0] == 1


def test_sourced_products_require_evidence_and_keep_identity_on_duplicate(cfg, conn, tmp_path):
    cfg.sources.append(cfg.sources[0].model_copy(update={"source_id": "identity", "purpose": "product_identity"}))
    sync_sources(conn, cfg)
    first = prod_row("a", "AAAA")
    verified = first.removesuffix(",approved\n") + "https://filings.example.test/etf,approved\n"
    file = write(tmp_path, "products.csv", PRODUCT_HDR + first)
    result = import_products(conn, cfg, file, source_id="identity")
    assert result.rejected == 1 and result.errors[0]["field"] == "identity_evidence_id"

    file.write_text(PRODUCT_HDR + verified)
    assert import_products(conn, cfg, file, source_id="identity").inserted == 1
    assert import_products(conn, cfg, file).skipped == 1
    row = conn.execute("SELECT identity_source_id, identity_evidence_id FROM funds").fetchone()
    assert tuple(row) == ("identity", "https://filings.example.test/etf")
    with pytest.raises(ValueError, match="purpose 'news'"):
        import_products(conn, cfg, file, source_id="demo_news_import")


def test_source_registry_migration_is_atomic_and_preserves_reports(tmp_path):
    old = tmp_path / "migrations"
    old.mkdir()
    (old / "001_init.sql").write_text((ROOT / "migrations" / "001_init.sql").read_text())
    with closing(connect(tmp_path / "db.sqlite3")) as conn:
        assert migrate(conn, old) == ["001_init"]
        with conn:
            conn.execute("INSERT INTO sources VALUES ('archived', 'manual_import', 0, 'unknown', NULL, 'metadata_only', 0, 0, 0, NULL)")
            conn.execute("INSERT INTO reports VALUES ('report', 'weekly', 'retrospective', '2026-10-01', "
                         "'2026-10-08', '2026-10-08T12:00:00Z', 'draft', '2026-10-08T12:00:00Z', '{}')")

        (old / "002_source_registry.sql").write_text("ALTER TABLE sources ADD COLUMN purpose TEXT; SELECT no_such_column;")
        with pytest.raises(sqlite3.OperationalError, match="no such column"):
            migrate(conn, old)
        assert "purpose" not in [r["name"] for r in conn.execute("PRAGMA table_info(sources)")]

        assert migrate(conn) == ["002_source_registry"]
        assert migrate(conn) == []
        assert conn.execute("SELECT snapshot_json FROM reports WHERE report_id='report'").fetchone()[0] == "{}"
        assert conn.execute("SELECT purpose FROM sources WHERE source_id='archived'").fetchone()[0] is None
        assert not list(conn.execute("PRAGMA foreign_key_check"))
