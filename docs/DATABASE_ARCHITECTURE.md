# County Field Database Architecture

## Canonical model

The project has one canonical working store: a versioned GeoPackage database.

```text
Immutable source releases
          |
          v
Temporary candidate GeoPackage
          |
   validation and diff
          |
          v
Accepted GeoPackage release
          |
          v
Queries, reports, indexes, and application exports
```

JSON is retained only as immutable input evidence or as a generated interchange export. It is not the continuing source of truth.

GeoPackage combines portable SQLite SQL storage with standards-based spatial tables in one file. The database remains usable without TrivialHTTP. TrivialHTTP may later expose narrowly controlled read and refresh operations to the browser.

## Current data layers

### Administration

Records county identity, schema migrations, source agencies, datasets, harvest runs, source releases, and source files.

### Classification

Records immutable County Field Map releases, sector source hashes, normalized practical-cell classifications, and review requests caused by later development.

Batch 006 imports the completed field ledger as the first accepted classification release.

### Source geometry

Future migrations will add normalized building, road, water, parcel, and address feature tables. Source releases remain immutable.

### Derived data

Future migrations will add feature-to-cell indexes, building clusters, road graphs, summaries, and application exports.

### Change history

New harvests are compared with accepted releases. Added, removed, geometry-changed, and attribute-changed features are recorded rather than overwriting history.

## Candidate-build contract

1. Preserve each source release unchanged.
2. Build a separate temporary GeoPackage.
3. Validate schema, integrity, foreign keys, migration hashes, source hashes, counts, and normalized identities.
4. Replace the named candidate only after validation succeeds.
5. Never modify an accepted release in place.
6. Archive the previous accepted database during promotion.

A failed build or refresh leaves the existing candidate and accepted databases unchanged.

## Stable identity

Source identifiers are retained but are not assumed to be permanent. Project-level feature identities will be assigned independently. Later refresh logic may match features using source IDs, geometry overlap, parcel identity, address, feature type, and content hashes.

## TrivialHTTP boundary

TrivialHTTP may later provide:

- read-only prepared queries;
- spatial lookup endpoints;
- database status and version information;
- controlled candidate-build and validation commands;
- export generation.

It must not expose unrestricted SQL to the browser. Command-line tools and TrivialHTTP must operate against the same database contract.
