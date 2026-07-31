CREATE TABLE classification_grid_calibration (
    classification_release_id INTEGER PRIMARY KEY,
    boundary_relative_path TEXT NOT NULL,
    boundary_sha256 TEXT NOT NULL,
    boundary_byte_length INTEGER NOT NULL,
    srs_id INTEGER NOT NULL,
    raw_min_x REAL NOT NULL,
    raw_min_y REAL NOT NULL,
    raw_max_x REAL NOT NULL,
    raw_max_y REAL NOT NULL,
    world_min_x REAL NOT NULL,
    world_min_y REAL NOT NULL,
    world_max_x REAL NOT NULL,
    world_max_y REAL NOT NULL,
    padding REAL NOT NULL,
    scale REAL NOT NULL,
    offset_x REAL NOT NULL,
    offset_y REAL NOT NULL,
    calibrated_at TEXT NOT NULL,
    CONSTRAINT calibration_boundary_size CHECK (boundary_byte_length > 0),
    CONSTRAINT calibration_srs CHECK (srs_id = 4326),
    CONSTRAINT calibration_raw_bounds CHECK (
        raw_min_x < raw_max_x AND raw_min_y < raw_max_y
    ),
    CONSTRAINT calibration_world_bounds CHECK (
        world_min_x < world_max_x AND world_min_y < world_max_y
    ),
    CONSTRAINT calibration_padding CHECK (padding >= 0),
    CONSTRAINT calibration_scale CHECK (scale > 0),
    CONSTRAINT calibration_release_fk FOREIGN KEY (classification_release_id)
        REFERENCES classification_release(classification_release_id)
);

CREATE VIEW classification_cell_spatial AS
SELECT
    c.classification_release_id,
    c.cell_id,
    c.sector_id,
    c.global_row,
    c.global_column,
    c.classification,
    g.srs_id,
    g.raw_min_x + (
        (g.world_min_x + (g.world_max_x - g.world_min_x) / 6.0 +
         (c.global_column - 1) * ((g.world_max_x - g.world_min_x) * 4.0 / 6.0 / 512.0)) -
        g.offset_x
    ) / g.scale AS min_x,
    g.raw_min_x + (
        (g.world_min_x + (g.world_max_x - g.world_min_x) * 5.0 / 6.0 +
         (c.global_column - 512) * ((g.world_max_x - g.world_min_x) * 4.0 / 6.0 / 512.0)) -
        g.offset_x
    ) / g.scale AS max_x,
    g.raw_max_y - (
        (g.world_min_y + c.global_row * ((g.world_max_y - g.world_min_y) / 512.0)) -
        g.offset_y
    ) / g.scale AS min_y,
    g.raw_max_y - (
        (g.world_min_y + (c.global_row - 1) * ((g.world_max_y - g.world_min_y) / 512.0)) -
        g.offset_y
    ) / g.scale AS max_y
FROM classification_cell c
JOIN classification_grid_calibration g
  ON g.classification_release_id = c.classification_release_id;

CREATE TABLE building_cell_relation (
    source_building_id INTEGER NOT NULL,
    classification_release_id INTEGER NOT NULL,
    global_row INTEGER NOT NULL,
    global_column INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    PRIMARY KEY (
        source_building_id,
        classification_release_id,
        global_row,
        global_column
    ),
    CONSTRAINT building_cell_relation_type CHECK (relation_type = 'intersects'),
    CONSTRAINT building_cell_source_fk FOREIGN KEY (source_building_id)
        REFERENCES source_building(source_building_id),
    CONSTRAINT building_cell_classification_fk FOREIGN KEY (
        classification_release_id, global_row, global_column
    ) REFERENCES classification_cell(
        classification_release_id, global_row, global_column
    )
);

CREATE INDEX building_cell_by_classification
    ON building_cell_relation(
        classification_release_id, global_row, global_column, source_building_id
    );

CREATE INDEX building_cell_by_source
    ON building_cell_relation(source_building_id);

CREATE UNIQUE INDEX classification_review_building_identity
    ON classification_review(
        classification_release_id,
        cell_id,
        trigger_dataset_id,
        trigger_source_feature_id,
        detected_in_release_id
    )
    WHERE trigger_dataset_id IS NOT NULL
      AND trigger_source_feature_id IS NOT NULL
      AND detected_in_release_id IS NOT NULL;
