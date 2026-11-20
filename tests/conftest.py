from pathlib import Path

import pytest

from etf_pilot.config import load_config
from etf_pilot.db import open_db

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_HDR = "fund_id,name,ticker,listing_venue,listing_country,product_type,issuer_id,currency,cik,series_id,class_id,inception_date,launch_date,launch_date_basis,closure_date,identity_evidence_id,review_status\n"
METRIC_HDR = "external_record_id,fund_id,metric_name,value,unit,currency,scope,asset_basis,as_of_date,effective_from,effective_to,available_at,available_at_precision,source_id,evidence_url,evidence_locator,revision,review_status\n"
NEWS_HDR = "external_record_id,source_id,title,url,published_at,date_precision,body_or_excerpt,permission_reference,retention_mode,ai_allowed\n"


@pytest.fixture
def cfg(tmp_path):
    return load_config(str(ROOT / "configs" / "demo.yaml"), root=tmp_path)


@pytest.fixture
def conn(cfg):
    c = open_db(cfg)
    yield c
    c.close()


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def metric_row(rid, fund, name, value, unit, as_of, basis="net", currency="USD", scope="product", rev=1, status="approved", eff_from="", eff_to=""):
    cur = currency if name in ("net_assets", "total_assets") else ""
    return f"{rid},{fund},{name},{value},{unit},{cur},{scope},{basis},{as_of},{eff_from},{eff_to},{as_of},date,demo_metrics_import,https://example.test/{fund},loc,{rev},{status}\n"


def prod_row(fid, ticker, launch="2020-01-01", basis="actual", closure="", venue="V1", name=None, status="approved"):
    return f"{fid},{name or fid + ' ETF'},{ticker},{venue},US,ETF,demo_capital,USD,,,,{launch},{launch},{basis},{closure},,{status}\n"
