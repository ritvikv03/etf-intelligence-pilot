CREATE TABLE feed_cursors (
  source_id TEXT PRIMARY KEY REFERENCES sources(source_id),
  endpoint TEXT NOT NULL,
  etag TEXT,
  last_modified TEXT
);
CREATE TABLE feed_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  checked_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('success','unchanged','failed')),
  inserted INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  detail TEXT
);
CREATE INDEX ix_feed_runs_source ON feed_runs(source_id, run_id);
CREATE TABLE product_tags (
  fund_id TEXT NOT NULL REFERENCES funds(fund_id),
  tag_id TEXT NOT NULL,
  PRIMARY KEY (fund_id, tag_id)
);
CREATE TABLE tag_reviews (
  fund_id TEXT PRIMARY KEY REFERENCES funds(fund_id),
  reviewer TEXT NOT NULL,
  reviewed_at TEXT NOT NULL
);
ALTER TABLE metric_observations ADD COLUMN period_start TEXT;
ALTER TABLE metric_observations ADD COLUMN period_end TEXT;
CREATE TABLE report_checkpoints (
  definition_id TEXT PRIMARY KEY,
  end_date TEXT NOT NULL,
  data_cutoff TEXT NOT NULL,
  report_id TEXT NOT NULL REFERENCES reports(report_id)
);
CREATE TABLE report_artifacts (
  report_id TEXT PRIMARY KEY REFERENCES reports(report_id),
  markdown TEXT NOT NULL,
  html TEXT NOT NULL,
  manifest TEXT NOT NULL
);
