# Browser Open-Review Layer

Batch 017 connects the read-only sectorized review bundle to the existing county map. The browser loads `index.json` once, then loads only the GeoJSON file for the active county sector. Leaving that sector releases the parsed sector document from application memory.

## Data location

The default browser path is:

```text
data/reviews/current/
```

The generated bundle remains outside Git. During Linux development, `data/reviews/current` may be a symbolic link to an accepted external bundle. For final offline packaging, copy the accepted bundle into that location as ordinary files.

A different HTTP-visible path may be selected without editing source:

```text
?reviews=/path/to/review-bundle
```

The path is interpreted relative to the TrivialHTTP document root. A raw operating-system path outside that root is not browser-accessible unless it is exposed through a directory or symbolic link beneath the document root.

## Validation and memory behavior

Before displaying reviews, the browser validates:

- bundle and sector schema identities;
- all 16 sector registry entries and their order;
- the completed classification release key and archive hash;
- county-boundary calibration bounds against the prepared browser boundary;
- exact sector-file byte length and SHA-256 digest;
- sector identity, practical-cell identity, counts, and trigger arrays.

Sector files are fetched with browser caching disabled. The loader retains only the currently selected sector document. The index remains loaded because it contains the county-wide counts and the path/hash registry for all sectors.

## Display

- County view: sectors are shaded by review-cell density.
- Sector view: inspection cells containing reviews are outlined in orange.
- Practical view: exact practical cells requiring review are outlined in orange.

The review layer is read-only. Classification clicks continue to affect only the classification ledger. The browser has no endpoint or command for accepting, dismissing, deferring, or otherwise changing SQL review records.

If the review bundle is absent or invalid, the map and classification ledger remain usable. The review status panel reports the problem without converting it into a fatal application error.
