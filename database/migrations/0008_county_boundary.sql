CREATE TABLE source_county_boundary (
    source_boundary_id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL UNIQUE,
    source_feature_id TEXT NOT NULL,
    source_ordinal INTEGER NOT NULL,
    geometry BLOB NOT NULL,
    geometry_type TEXT NOT NULL,
    geometry_sha256 TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    attributes_sha256 TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    min_x REAL NOT NULL,
    min_y REAL NOT NULL,
    max_x REAL NOT NULL,
    max_y REAL NOT NULL,
    CONSTRAINT source_boundary_release_feature_unique
        UNIQUE (release_id, source_feature_id),
    CONSTRAINT source_boundary_single_feature CHECK (source_ordinal = 1),
    CONSTRAINT source_boundary_geometry_type CHECK
        (geometry_type IN ('Polygon', 'MultiPolygon')),
    CONSTRAINT source_boundary_bounds CHECK
        (min_x < max_x AND min_y < max_y),
    CONSTRAINT source_boundary_release_fk FOREIGN KEY (release_id)
        REFERENCES source_release(release_id)
);

CREATE INDEX source_county_boundary_bounds
    ON source_county_boundary(min_x, max_x, min_y, max_y);

INSERT INTO gpkg_contents(
    table_name, data_type, identifier, description, srs_id
) VALUES (
    'source_county_boundary', 'features', 'Kane County boundary',
    'Immutable normalized Kane County boundary grouped by source release.', 4326
);

INSERT INTO gpkg_geometry_columns(
    table_name, column_name, geometry_type_name, srs_id, z, m
) VALUES (
    'source_county_boundary', 'geometry', 'GEOMETRY', 4326, 0, 0
);

ALTER TABLE classification_grid_calibration
    ADD COLUMN boundary_release_id INTEGER
    REFERENCES source_release(release_id);

CREATE UNIQUE INDEX classification_grid_boundary_release
    ON classification_grid_calibration(boundary_release_id)
    WHERE boundary_release_id IS NOT NULL;
