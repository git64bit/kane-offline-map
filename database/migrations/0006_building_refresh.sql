ALTER TABLE source_release ADD COLUMN superseded_at TEXT;

CREATE TABLE building_release_comparison (
    comparison_id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL UNIQUE,
    previous_release_id INTEGER NOT NULL,
    candidate_release_id INTEGER NOT NULL UNIQUE,
    compared_at TEXT NOT NULL,
    previous_feature_count INTEGER NOT NULL,
    candidate_feature_count INTEGER NOT NULL,
    added_count INTEGER NOT NULL,
    removed_count INTEGER NOT NULL,
    unchanged_count INTEGER NOT NULL,
    geometry_changed_count INTEGER NOT NULL,
    attributes_changed_count INTEGER NOT NULL,
    modified_count INTEGER NOT NULL,
    CONSTRAINT building_comparison_release_pair_unique
        UNIQUE (previous_release_id, candidate_release_id),
    CONSTRAINT building_comparison_counts_nonnegative CHECK (
        previous_feature_count >= 0 AND candidate_feature_count >= 0 AND
        added_count >= 0 AND removed_count >= 0 AND unchanged_count >= 0 AND
        geometry_changed_count >= 0 AND attributes_changed_count >= 0 AND
        modified_count >= 0
    ),
    CONSTRAINT building_comparison_previous_total CHECK (
        previous_feature_count = removed_count + unchanged_count +
        geometry_changed_count + attributes_changed_count + modified_count
    ),
    CONSTRAINT building_comparison_candidate_total CHECK (
        candidate_feature_count = added_count + unchanged_count +
        geometry_changed_count + attributes_changed_count + modified_count
    ),
    CONSTRAINT building_comparison_run_fk FOREIGN KEY (run_id)
        REFERENCES harvest_run(run_id),
    CONSTRAINT building_comparison_previous_fk FOREIGN KEY (previous_release_id)
        REFERENCES source_release(release_id),
    CONSTRAINT building_comparison_candidate_fk FOREIGN KEY (candidate_release_id)
        REFERENCES source_release(release_id)
);

CREATE TABLE building_feature_change (
    change_id INTEGER PRIMARY KEY,
    comparison_id INTEGER NOT NULL,
    source_feature_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    previous_source_building_id INTEGER,
    candidate_source_building_id INTEGER,
    previous_content_sha256 TEXT,
    candidate_content_sha256 TEXT,
    CONSTRAINT building_feature_change_unique
        UNIQUE (comparison_id, source_feature_id),
    CONSTRAINT building_feature_change_type CHECK (
        change_type IN (
            'added', 'removed', 'unchanged', 'geometry_changed',
            'attributes_changed', 'modified'
        )
    ),
    CONSTRAINT building_feature_change_shape CHECK (
        (change_type = 'added' AND previous_source_building_id IS NULL AND
            candidate_source_building_id IS NOT NULL AND
            previous_content_sha256 IS NULL AND candidate_content_sha256 IS NOT NULL)
        OR
        (change_type = 'removed' AND previous_source_building_id IS NOT NULL AND
            candidate_source_building_id IS NULL AND
            previous_content_sha256 IS NOT NULL AND candidate_content_sha256 IS NULL)
        OR
        (change_type NOT IN ('added', 'removed') AND
            previous_source_building_id IS NOT NULL AND
            candidate_source_building_id IS NOT NULL AND
            previous_content_sha256 IS NOT NULL AND candidate_content_sha256 IS NOT NULL)
    ),
    CONSTRAINT building_feature_change_comparison_fk FOREIGN KEY (comparison_id)
        REFERENCES building_release_comparison(comparison_id),
    CONSTRAINT building_feature_change_previous_fk FOREIGN KEY (previous_source_building_id)
        REFERENCES source_building(source_building_id),
    CONSTRAINT building_feature_change_candidate_fk FOREIGN KEY (candidate_source_building_id)
        REFERENCES source_building(source_building_id)
);

CREATE INDEX building_feature_change_type
    ON building_feature_change(comparison_id, change_type, source_feature_id);

CREATE INDEX building_comparison_previous_release
    ON building_release_comparison(previous_release_id, candidate_release_id);
