# County Field Map storage endpoint

Current endpoint:

```text
GET  /__county_field_map/sector-state
GET  /__county_field_map/sector-state/N11-E06.json
HEAD /__county_field_map/sector-state/N11-E06.json
PUT  /__county_field_map/sector-state/N11-E06.json
```

The legacy Kane-Map endpoint remains available so an existing USB installation can be migrated without losing classification state:

```text
/__kane_map/sector-state
```

Only the 16 canonical sectors are accepted: N11–N14 by E06–E09. Sector files are stored under `project-data/sectors` relative to the served root. Writes use a temporary file, flush, and atomic replacement.
