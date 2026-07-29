CREATE TABLE project_setting (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE county (
    county_id INTEGER PRIMARY KEY,
    county_name TEXT NOT NULL,
    state_name TEXT NOT NULL,
    state_code TEXT NOT NULL,
    fips_code TEXT NOT NULL UNIQUE,
    canonical_srs_id INTEGER,
    created_at TEXT NOT NULL,
    CONSTRAINT county_state_code CHECK (length(state_code) = 2),
    CONSTRAINT county_fips CHECK (length(fips_code) = 5),
    CONSTRAINT county_srs_fk FOREIGN KEY (canonical_srs_id)
        REFERENCES gpkg_spatial_ref_sys(srs_id)
);

CREATE TABLE source_agency (
    agency_id INTEGER PRIMARY KEY,
    agency_key TEXT NOT NULL UNIQUE,
    agency_name TEXT NOT NULL,
    jurisdiction TEXT,
    homepage_uri TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE dataset (
    dataset_id INTEGER PRIMARY KEY,
    county_id INTEGER NOT NULL,
    agency_id INTEGER,
    dataset_key TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    feature_class TEXT NOT NULL,
    source_id_policy TEXT,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    CONSTRAINT dataset_key_unique UNIQUE (county_id, dataset_key),
    CONSTRAINT dataset_county_fk FOREIGN KEY (county_id)
        REFERENCES county(county_id),
    CONSTRAINT dataset_agency_fk FOREIGN KEY (agency_id)
        REFERENCES source_agency(agency_id)
);

CREATE TABLE source_release (
    release_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL,
    release_key TEXT NOT NULL,
    source_version TEXT,
    source_published_at TEXT,
    harvested_at TEXT NOT NULL,
    accepted_at TEXT,
    source_uri TEXT,
    content_sha256 TEXT,
    status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    CONSTRAINT source_release_unique UNIQUE (dataset_id, release_key),
    CONSTRAINT source_release_status CHECK
        (status IN ('candidate', 'accepted', 'superseded', 'rejected')),
    CONSTRAINT source_release_dataset_fk FOREIGN KEY (dataset_id)
        REFERENCES dataset(dataset_id)
);

CREATE UNIQUE INDEX source_release_one_accepted
    ON source_release(dataset_id)
    WHERE status = 'accepted';

CREATE TABLE source_file (
    source_file_id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    media_type TEXT,
    byte_length INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    preserved_at TEXT NOT NULL,
    CONSTRAINT source_file_unique UNIQUE (release_id, relative_path),
    CONSTRAINT source_file_size CHECK (byte_length >= 0),
    CONSTRAINT source_file_release_fk FOREIGN KEY (release_id)
        REFERENCES source_release(release_id)
);

CREATE TABLE harvest_run (
    run_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL,
    previous_release_id INTEGER,
    candidate_release_id INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    error_message TEXT,
    CONSTRAINT harvest_status CHECK
        (status IN ('started', 'validated', 'accepted', 'failed', 'cancelled')),
    CONSTRAINT harvest_dataset_fk FOREIGN KEY (dataset_id)
        REFERENCES dataset(dataset_id),
    CONSTRAINT harvest_previous_fk FOREIGN KEY (previous_release_id)
        REFERENCES source_release(release_id),
    CONSTRAINT harvest_candidate_fk FOREIGN KEY (candidate_release_id)
        REFERENCES source_release(release_id)
);
