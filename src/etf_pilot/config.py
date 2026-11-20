"""Validated client configuration. Unknown keys and enum values raise readable errors."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AIConfig(_Strict):
    enabled: bool = False
    provider: Literal["ollama"] = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model_env_var: str = "OLLAMA_MODEL"
    send_only_permitted_content: bool = True

    @model_validator(mode="after")
    def _local_only(self):
        if not (self.base_url.startswith("http://127.0.0.1") or self.base_url.startswith("http://localhost")):
            raise ValueError("ai.base_url must be a local endpoint; hosted models are not permitted")
        return self


class ReviewConfig(_Strict):
    require_approval_before_finalize: bool = True
    auto_accept_ai_events: bool = False


class UniverseConfig(_Strict):
    listing_country: str
    product_type: str
    asset_classes: list[Literal["equity", "fixed_income"]]
    issuer_ids: list[str]


class Pillar(_Strict):
    id: str
    label: str


class SourceConfig(_Strict):
    source_id: str
    source_type: Literal["manual_import", "sec_nport_local", "rss"]
    enabled: bool
    permission_status: str
    permission_reference: Optional[str] = None
    retention_mode: Literal["full", "metadata_only"]
    ai_allowed: bool = False
    internal_report_allowed: bool = False
    redistribution_allowed: bool = False
    coverage_notes: str = ""


class ClientConfig(_Strict):
    client_id: str
    client_display_name: str
    mode: Literal["demo", "pilot"]
    demo_banner: Optional[str] = None
    database_path: str
    export_dir: str
    report_timezone: str
    report_schedule: Literal["weekly", "daily", "monthly"]
    report_mode: Literal["retrospective", "as_known_then"]
    primary_asset_metric: Literal["net_assets"]
    primary_fee_metric: Literal["expense_ratio_net", "expense_ratio_gross", "management_fee"]
    report_currency: str
    require_same_group_as_of_date: bool
    allow_automatic_daily_forward_fill: bool
    max_asset_age_days: int
    max_fee_age_days: int
    max_fee_asset_date_gap_days: int
    allow_revenue_proxy: bool
    ai: AIConfig
    review: ReviewConfig
    universe: UniverseConfig
    watchlist_issuer_ids: list[str] = []
    pillars: list[Pillar]
    sources: list[SourceConfig]
    root: Path = Path(".")  # set by loader

    @model_validator(mode="after")
    def _checks(self):
        if self.mode == "demo":
            if "demo" not in self.database_path:
                raise ValueError("demo mode requires a database_path containing 'demo' (separate from pilot data)")
            if any(s.source_type == "rss" and s.enabled for s in self.sources):
                raise ValueError("demo mode must not enable live network sources")
            if not self.demo_banner:
                raise ValueError("demo mode requires demo_banner")
        else:
            if "demo" in self.database_path or "demo" in self.export_dir:
                raise ValueError("pilot mode must not use demo database/export paths")
            if any(s.permission_status == "synthetic_fixture" for s in self.sources):
                raise ValueError("pilot mode must not contain synthetic fixture sources")
        if self.allow_automatic_daily_forward_fill:
            raise ValueError("allow_automatic_daily_forward_fill=true is not supported")
        if self.report_mode == "as_known_then":
            raise ValueError("report_mode as_known_then is not implemented in Milestone 1")
        if self.ai.enabled:
            raise ValueError("ai.enabled=true is not implemented in Milestone 1 (templates only)")
        for s in self.sources:
            if s.enabled and s.permission_status in ("permission_required", "unknown"):
                raise ValueError(f"source {s.source_id}: cannot enable with permission_status={s.permission_status}")
        return self

    @property
    def db_file(self) -> Path:
        return self.root / self.database_path

    @property
    def export_path(self) -> Path:
        return self.root / self.export_dir


class ConfigError(Exception):
    pass


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse(p: Path, root: Path) -> ClientConfig:
    data = yaml.safe_load(p.read_text())
    try:
        return ClientConfig(**data, root=root)
    except ValidationError as e:
        lines = [f"  {'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise ConfigError(f"invalid config {p}:\n" + "\n".join(lines)) from e


def load_config(name_or_path: str, root: Path | None = None) -> ClientConfig:
    """Load by YAML path or by client_id (searches configs/*.yaml)."""
    root = root or project_root()
    if name_or_path.endswith((".yaml", ".yml")):
        p = Path(name_or_path)
        if not p.exists():
            raise ConfigError(f"config file not found: {p}")
        return _parse(p, root)
    for p in sorted((root / "configs").glob("*.yaml")):
        data = yaml.safe_load(p.read_text())
        if isinstance(data, dict) and data.get("client_id") == name_or_path:
            return _parse(p, root)
    raise ConfigError(f"no config with client_id '{name_or_path}' in {root / 'configs'}")
