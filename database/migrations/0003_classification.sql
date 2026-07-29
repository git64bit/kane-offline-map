CREATE TABLE classification_release (
    classification_release_id INTEGER PRIMARY KEY,
    county_id INTEGER NOT NULL,
    release_key TEXT NOT NULL UNIQUE,
    source_format TEXT NOT NULL,
    source_version INTEGER NOT NULL,
    source_archive_sha256 TEXT NOT NULL,
    source_created_at TEXT,
    imported_at TEXT NOT NULL,
    status TEXT NOT NULL,
    sector_count INTEGER NOT NULL,
    inspection_cell_count INTEGER NOT NULL,
    practical_cell_count INTEGER NOT NULL,
    discovered_count INTEGER NOT NULL,
    muted_count INTEGER NOT NULL,
    undiscovered_count INTEGER NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    CONSTRAINT classification_status CHECK
        (status IN ('candidate', 'accepted', 'superseded', 'rejected')),
    CONSTRAINT classification_counts CHECK (
        sector_count >= 0 AND
        inspection_cell_count >= 0 AND
        practical_cell_count >= 0 AND
        discovered_count >= 0 AND
        muted_count >= 0 AND
        undiscovered_count >= 0 AND
        discovered_count + muted_count + undiscovered_count = practical_cell_count
    ),
    CONSTRAINT classification_county_fk FOREIGN KEY (county_id)
        REFERENCES county(county_id)
);

CREATE UNIQUE INDEX classification_one_accepted
    ON classification_release(county_id)
    WHERE status = 'accepted';

CREATE TABLE classification_sector (
    classification_sector_id INTEGER PRIMARY KEY,
    classification_release_id INTEGER NOT NULL,
    sector_id TEXT NOT NULL,
    source_relative_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_updated_at TEXT,
    inspection_cell_count INTEGER NOT NULL,
    practical_cell_count INTEGER NOT NULL,
    discovered_count INTEGER NOT NULL,
    muted_count INTEGER NOT NULL,
    undiscovered_count INTEGER NOT NULL,
    CONSTRAINT classification_sector_unique
        UNIQUE (classification_release_id, sector_id),
    CONSTRAINT classification_sector_counts CHECK (
        inspection_cell_count >= 0 AND
        practical_cell_count >= 0 AND
        discovered_count >= 0 AND
        muted_count >= 0 AND
        undiscovered_count >= 0 AND
        discovered_count + muted_count + undiscovered_count = practical_cell_count
    ),
    CONSTRAINT classification_sector_release_fk
        FOREIGN KEY (classification_release_id)
        REFERENCES classification_release(classification_release_id)
);

CREATE TABLE classification_cell (
    classification_release_id INTEGER NOT NULL,
    cell_id TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    sector_north INTEGER NOT NULL,
    sector_east INTEGER NOT NULL,
    inspection_row INTEGER NOT NULL,
    inspection_column INTEGER NOT NULL,
    practical_row INTEGER NOT NULL,
    practical_column INTEGER NOT NULL,
    global_row INTEGER NOT NULL,
    global_column INTEGER NOT NULL,
    classification TEXT NOT NULL,
    PRIMARY KEY (classification_release_id, cell_id),
    CONSTRAINT classification_cell_grid_unique
        UNIQUE (classification_release_id, global_row, global_column),
    CONSTRAINT classification_cell_state CHECK
        (classification IN ('discovered', 'muted', 'undiscovered')),
    CONSTRAINT classification_inspection_row CHECK
        (inspection_row BETWEEN 1 AND 16),
    CONSTRAINT classification_inspection_column CHECK
        (inspection_column BETWEEN 1 AND 16),
    CONSTRAINT classification_practical_row CHECK
        (practical_row BETWEEN 1 AND 8),
    CONSTRAINT classification_practical_column CHECK
        (practical_column BETWEEN 1 AND 8),
    CONSTRAINT classification_global_row CHECK
        (global_row BETWEEN 1 AND 512),
    CONSTRAINT classification_global_column CHECK
        (global_column BETWEEN 1 AND 512),
    CONSTRAINT classification_cell_release_fk
        FOREIGN KEY (classification_release_id)
        REFERENCES classification_release(classification_release_id)
);

CREATE INDEX classification_cell_sector
    ON classification_cell(classification_release_id, sector_id);

CREATE INDEX classification_cell_state
    ON classification_cell(classification_release_id, classification);

CREATE TABLE classification_review (
    review_id INTEGER PRIMARY KEY,
    classification_release_id INTEGER NOT NULL,
    cell_id TEXT NOT NULL,
    trigger_dataset_id INTEGER,
    trigger_source_feature_id TEXT,
    previous_classification TEXT NOT NULL,
    recommended_classification TEXT,
    detected_in_release_id INTEGER,
    detected_at TEXT NOT NULL,
    review_status TEXT NOT NULL,
    resolution_note TEXT NOT NULL DEFAULT '',
    resolved_at TEXT,
    CONSTRAINT review_previous_state CHECK
        (previous_classification IN ('discovered', 'muted', 'undiscovered')),
    CONSTRAINT review_recommended_state CHECK
        (recommended_classification IS NULL OR
         recommended_classification IN ('discovered', 'muted', 'undiscovered')),
    CONSTRAINT review_status CHECK
        (review_status IN ('open', 'accepted', 'dismissed', 'deferred')),
    CONSTRAINT review_classification_fk
        FOREIGN KEY (classification_release_id, cell_id)
        REFERENCES classification_cell(classification_release_id, cell_id),
    CONSTRAINT review_dataset_fk FOREIGN KEY (trigger_dataset_id)
        REFERENCES dataset(dataset_id),
    CONSTRAINT review_release_fk FOREIGN KEY (detected_in_release_id)
        REFERENCES source_release(release_id)
);
