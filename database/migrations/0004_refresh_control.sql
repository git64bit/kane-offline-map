CREATE TABLE refresh_issue (
    issue_id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    severity TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    entity_type TEXT,
    entity_key TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_note TEXT NOT NULL DEFAULT '',
    CONSTRAINT refresh_issue_severity CHECK
        (severity IN ('info', 'warning', 'error')),
    CONSTRAINT refresh_issue_run_fk FOREIGN KEY (run_id)
        REFERENCES harvest_run(run_id)
);

CREATE INDEX refresh_issue_run
    ON refresh_issue(run_id, severity);

CREATE TABLE release_promotion (
    promotion_id INTEGER PRIMARY KEY,
    county_id INTEGER NOT NULL,
    candidate_path TEXT NOT NULL,
    accepted_path TEXT NOT NULL,
    archived_path TEXT,
    candidate_sha256 TEXT NOT NULL,
    previous_sha256 TEXT,
    promoted_at TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    CONSTRAINT release_promotion_county_fk FOREIGN KEY (county_id)
        REFERENCES county(county_id)
);
