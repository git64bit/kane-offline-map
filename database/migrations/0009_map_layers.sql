CREATE TABLE source_map_feature (
    source_map_feature_id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL,
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
    CONSTRAINT source_map_feature_release_feature_unique
        UNIQUE (release_id, source_feature_id),
    CONSTRAINT source_map_feature_release_ordinal_unique
        UNIQUE (release_id, source_ordinal),
    CONSTRAINT source_map_feature_ordinal CHECK (source_ordinal >= 1),
    CONSTRAINT source_map_feature_geometry_type CHECK
        (geometry_type IN ('LineString', 'MultiLineString', 'Polygon', 'MultiPolygon')),
    CONSTRAINT source_map_feature_bounds CHECK
        (min_x <= max_x AND min_y <= max_y),
    CONSTRAINT source_map_feature_release_fk FOREIGN KEY (release_id)
        REFERENCES source_release(release_id)
);

CREATE INDEX source_map_feature_release
    ON source_map_feature(release_id, source_feature_id);

CREATE INDEX source_map_feature_bounds
    ON source_map_feature(min_x, max_x, min_y, max_y);

INSERT INTO gpkg_contents(
    table_name, data_type, identifier, description, srs_id
) VALUES (
    'source_map_feature', 'features', 'Kane County roads and water',
    'Immutable normalized road and water features grouped by source release.', 4326
);

INSERT INTO gpkg_geometry_columns(
    table_name, column_name, geometry_type_name, srs_id, z, m
) VALUES (
    'source_map_feature', 'geometry', 'GEOMETRY', 4326, 0, 0
);
