CREATE TABLE sources (
  source_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, enabled INTEGER NOT NULL,
  permission_status TEXT NOT NULL, permission_reference TEXT, retention_mode TEXT NOT NULL,
  ai_allowed INTEGER NOT NULL, internal_report_allowed INTEGER NOT NULL,
  redistribution_allowed INTEGER NOT NULL, coverage_notes TEXT
);
CREATE TABLE issuers (issuer_id TEXT PRIMARY KEY, brand TEXT NOT NULL);
CREATE TABLE funds (
  fund_id TEXT PRIMARY KEY, name TEXT NOT NULL, ticker TEXT NOT NULL, listing_venue TEXT,
  listing_country TEXT NOT NULL, product_type TEXT NOT NULL,
  issuer_id TEXT NOT NULL REFERENCES issuers(issuer_id), currency TEXT NOT NULL,
  inception_date TEXT, launch_date TEXT,
  launch_date_basis TEXT NOT NULL CHECK (launch_date_basis IN ('actual','inception_proxy','conversion','unknown')),
  closure_date TEXT, identity_evidence_id TEXT, review_status TEXT NOT NULL
);
CREATE TABLE fund_identifiers (
  fund_id TEXT NOT NULL REFERENCES funds(fund_id), id_type TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (fund_id, id_type, value)
);
CREATE TABLE ingestion_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, file TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
  inserted INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE rejected_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES ingestion_runs(run_id),
  file TEXT NOT NULL, row_number INTEGER NOT NULL, field TEXT, message TEXT NOT NULL, suggestion TEXT
);
CREATE TABLE evidence (
  evidence_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id),
  external_record_id TEXT NOT NULL, revision INTEGER NOT NULL, url TEXT, canonical_url TEXT,
  title TEXT NOT NULL, published_at TEXT, date_precision TEXT NOT NULL,
  first_observed_at TEXT NOT NULL, retrieved_at TEXT NOT NULL,
  body TEXT, content_hash TEXT NOT NULL, permission_reference TEXT, retention_mode TEXT NOT NULL,
  ai_allowed INTEGER NOT NULL,
  UNIQUE (source_id, external_record_id, content_hash)
);
CREATE UNIQUE INDEX ix_evidence_canon ON evidence(canonical_url, content_hash) WHERE canonical_url IS NOT NULL;
CREATE TABLE evidence_associations (
  evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id), source_id TEXT NOT NULL,
  external_record_id TEXT NOT NULL, observed_at TEXT NOT NULL,
  PRIMARY KEY (evidence_id, source_id, external_record_id)
);
CREATE TABLE events (
  event_id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
  event_type TEXT NOT NULL, fund_id TEXT REFERENCES funds(fund_id), candidate_fund_ids TEXT NOT NULL,
  effective_date TEXT, first_observed_at TEXT NOT NULL, proposed_by TEXT NOT NULL,
  review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','accepted','rejected','deferred')),
  approved_at TEXT
);
CREATE TABLE metric_observations (
  obs_id TEXT PRIMARY KEY, external_record_id TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES sources(source_id),
  fund_id TEXT NOT NULL REFERENCES funds(fund_id), metric_name TEXT NOT NULL, value TEXT NOT NULL,
  unit TEXT NOT NULL, currency TEXT, scope TEXT NOT NULL, asset_basis TEXT NOT NULL,
  as_of_date TEXT NOT NULL, effective_from TEXT, effective_to TEXT, available_at TEXT,
  available_at_precision TEXT, first_observed_at TEXT NOT NULL, evidence_url TEXT, evidence_locator TEXT,
  revision INTEGER NOT NULL, review_status TEXT NOT NULL, value_original TEXT NOT NULL, unit_original TEXT NOT NULL,
  UNIQUE (source_id, external_record_id, revision)
);
CREATE TABLE review_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  reviewer TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT, previous_value TEXT, new_value TEXT, at TEXT NOT NULL
);
CREATE TABLE reports (
  report_id TEXT PRIMARY KEY, profile TEXT NOT NULL, mode TEXT NOT NULL, window_start TEXT NOT NULL,
  window_end TEXT NOT NULL, data_cutoff TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
  snapshot_json TEXT NOT NULL
);
