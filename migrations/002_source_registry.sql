ALTER TABLE sources ADD COLUMN purpose TEXT;
ALTER TABLE sources ADD COLUMN endpoint TEXT;
ALTER TABLE sources ADD COLUMN owner TEXT;
ALTER TABLE sources ADD COLUMN update_frequency TEXT;
ALTER TABLE funds ADD COLUMN identity_source_id TEXT REFERENCES sources(source_id);

CREATE TABLE source_import_runs (
  run_id INTEGER NOT NULL REFERENCES ingestion_runs(run_id),
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  inserted INTEGER NOT NULL,
  skipped INTEGER NOT NULL,
  rejected INTEGER NOT NULL,
  PRIMARY KEY (run_id, source_id)
);
CREATE INDEX ix_source_import_runs_source ON source_import_runs(source_id, run_id);
