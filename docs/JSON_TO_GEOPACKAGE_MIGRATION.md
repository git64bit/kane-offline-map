# Completed Ledger Migration

## Accepted immutable input

The completed field ledger is preserved as `database/input/sectors.zip`. It contains 16 legacy sector-state JSON files using:

```text
format: kane-map-sector-state
version: 1
county: Kane County, Illinois
```

Archive SHA-256:

```text
19506566f787b11a02036dce8bf800a33b0a64219046c5e0b89d474b862f09d2
```

Verified totals:

- 16 sectors
- 4,096 inspection cells
- 262,144 practical cells
- 72,705 discovered cells
- 189,439 muted cells
- 0 undiscovered cells

The archive is historical evidence and a reproducible migration input. It is not the continuing operational dataset.

## Import rules

1. The original archive and member bytes remain unchanged.
2. The archive and every sector member receive a SHA-256 record.
3. One accepted `classification_release` row identifies the baseline.
4. One `classification_sector` row records every source member and its counts.
5. One `classification_cell` row records every practical cell.
6. Legacy practical `active` becomes SQL `discovered`.
7. Legacy practical `muted` remains SQL `muted`.
8. Any missing practical classification rejects this completed release.
9. Duplicate, malformed, foreign-county, overlapping, unsafe, or out-of-range identifiers reject the build.
10. Inspection and sector summaries must agree with their practical cells.
11. Import and validation occur against a temporary candidate database.
12. The existing candidate is replaced only after the new build passes.

## Grid identity

Each practical cell retains its source identity and normalized coordinates:

```text
N11-E06:r03c10:f08c04
```

Normalized columns record:

- sector north and east labels;
- inspection row and column, 1 through 16;
- practical row and column, 1 through 8;
- county-global row and column, 1 through 512.

The normalized origin is:

```text
N11-E06:r01c01:f01c01 = global row 1, column 1
```

The opposite endpoint is:

```text
N14-E09:r16c16:f08c08 = global row 512, column 512
```

Geometry is intentionally deferred until the county grid envelope and canonical coordinate reference system are reconciled with the prepared spatial source files.

## Upgrade behavior

The accepted classification is a baseline release, not a permanent exclusion mask. Future countywide source harvests must compare all new source features against the previous accepted release. A new feature intersecting a muted cell creates a review item instead of being silently discarded.
