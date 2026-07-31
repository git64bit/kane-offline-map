(function attachReviewBundleLoader(global) {
  "use strict";

  const CFM = global.CountyFieldMap;
  const K = CFM.constants;
  const G = CFM.grid;
  const INDEX_SCHEMA = "kane-offline-map-open-review-bundle";
  const SECTOR_SCHEMA = "kane-offline-map-open-review-sector";
  const SCHEMA_VERSION = 1;

  function createReviewBundleLoader(options = {}) {
    const configured = global.CountyFieldMapConfig || {};
    const query = new URLSearchParams(global.location.search || "");
    const explicitRoot = query.get("reviews") || query.get("reviewBundle") || query.get("review-bundle");
    const roots = unique([
      explicitRoot,
      options.bundlePath,
      configured.reviewBundlePath,
      "data/reviews/current"
    ].filter(Boolean));
    let bundleRoot = null;
    let indexDocument = null;
    let registry = new Map();
    let loadedSector = null;
    let sectorData = emptySectorData();
    let loadGeneration = 0;

    async function loadIndex(boundaryBounds) {
      let lastError = null;
      for (const root of roots) {
        try {
          const document = await fetchJson(join(root, "index.json"));
          validateIndex(document, boundaryBounds);
          bundleRoot = stripSlash(root);
          indexDocument = document;
          registry = new Map(document.sectors.map((item) => [item.sector_id, item]));
          return indexInfo();
        } catch (error) {
          lastError = error;
          if (explicitRoot) break;
        }
      }
      throw new Error(`Open-review bundle could not be loaded. ${lastError ? lastError.message : "No review path succeeded."}`);
    }

    async function loadSector(sector) {
      if (!indexDocument || !bundleRoot) throw new Error("Review bundle index must load before sector reviews.");
      if (!G.parseSector(sector)) throw new Error(`Invalid review sector ${sector}.`);
      if (loadedSector === sector) return sectorData;
      const item = registry.get(sector);
      if (!item) throw new Error(`Review bundle index does not contain ${sector}.`);
      const generation = ++loadGeneration;
      const document = await fetchJson(join(bundleRoot, item.relative_path), item);
      const next = normalizeSector(document, sector, item, indexDocument);
      if (generation === loadGeneration) {
        loadedSector = sector;
        sectorData = next;
      }
      return next;
    }

    function releaseSector() {
      loadGeneration += 1;
      loadedSector = null;
      sectorData = emptySectorData();
    }

    function indexInfo() {
      if (!indexDocument) return null;
      return {
        root: bundleRoot,
        generatedAt: indexDocument.generated_at,
        summary: indexDocument.summary,
        sectors: indexDocument.sectors.map((item) => ({ ...item }))
      };
    }

    return {
      loadIndex,
      loadSector,
      releaseSector,
      indexInfo,
      currentSector: () => loadedSector,
      currentData: () => sectorData,
      available: () => Boolean(indexDocument)
    };
  }

  function validateIndex(document, boundaryBounds) {
    if (!document || document.schema !== INDEX_SCHEMA || document.schema_version !== SCHEMA_VERSION) {
      throw new Error("Review bundle index schema identity is invalid.");
    }
    if (!Array.isArray(document.sectors) || !document.summary || !document.calibration) {
      throw new Error("Review bundle index is incomplete.");
    }
    const codes = document.sectors.map((item) => item && item.sector_id);
    if (JSON.stringify(codes) !== JSON.stringify(G.sectorCodes)) {
      throw new Error("Review bundle sector registry is incomplete or out of order.");
    }
    document.sectors.forEach((item) => validateRegistryItem(item));
    const release = document.accepted_releases && document.accepted_releases.classification;
    if (!release || release.release_key !== K.CLASSIFICATION_RELEASE_KEY ||
        release.source_archive_sha256 !== K.CLASSIFICATION_ARCHIVE_SHA256) {
      throw new Error("Review bundle classification release does not match this application.");
    }
    validateBoundaryBounds(document.calibration.bounds, boundaryBounds);
    const totalCells = document.sectors.reduce((sum, item) => sum + item.review_cell_count, 0);
    const totalReviews = document.sectors.reduce((sum, item) => sum + item.open_review_count, 0);
    if (document.summary.review_cell_count !== totalCells || document.summary.open_review_count !== totalReviews) {
      throw new Error("Review bundle index summary is inconsistent.");
    }
  }

  function validateRegistryItem(item) {
    if (!item || !G.parseSector(item.sector_id)) throw new Error("Review bundle contains an invalid sector item.");
    if (item.relative_path !== `sectors/${item.sector_id}.geojson`) {
      throw new Error(`Review bundle path is invalid for ${item.sector_id}.`);
    }
    ["review_cell_count", "open_review_count", "byte_length"].forEach((key) => {
      if (!Number.isInteger(item[key]) || item[key] < 0) throw new Error(`Review bundle ${key} is invalid.`);
    });
    if (!/^[0-9a-f]{64}$/.test(String(item.sha256 || ""))) throw new Error("Review bundle sector hash is invalid.");
  }

  function validateBoundaryBounds(expected, actual) {
    if (!expected || !actual) throw new Error("Review bundle boundary calibration is unavailable.");
    const pairs = [
      [expected.min_x, actual.minX], [expected.min_y, actual.minY],
      [expected.max_x, actual.maxX], [expected.max_y, actual.maxY]
    ];
    if (pairs.some(([a, b]) => !Number.isFinite(a) || !Number.isFinite(b) || Math.abs(a - b) > 0.00002)) {
      throw new Error("Review bundle boundary does not match the prepared county boundary.");
    }
  }

  function normalizeSector(document, sector, item, index) {
    if (!document || document.type !== "FeatureCollection" || document.schema !== SECTOR_SCHEMA ||
        document.schema_version !== SCHEMA_VERSION || document.sector_id !== sector) {
      throw new Error(`Review sector ${sector} schema identity is invalid.`);
    }
    ["generated_at", "source_database", "accepted_releases", "calibration"].forEach((key) => {
      if (JSON.stringify(document[key]) !== JSON.stringify(index[key])) {
        throw new Error(`Review sector ${sector} ${key} does not match the index.`);
      }
    });
    if (!Array.isArray(document.features) || !document.summary) {
      throw new Error(`Review sector ${sector} is incomplete.`);
    }
    const cells = document.features.map((feature) => normalizeFeature(feature, sector));
    const unique = new Set(cells.map((cell) => cell.index));
    const reviewCount = cells.reduce((sum, cell) => sum + cell.reviewCount, 0);
    if (unique.size !== cells.length || cells.length !== item.review_cell_count ||
        reviewCount !== item.open_review_count || document.summary.review_cell_count !== cells.length ||
        document.summary.open_review_count !== reviewCount) {
      throw new Error(`Review sector ${sector} counts or cell identities are inconsistent.`);
    }
    return { sector, cells, reviewCount, cellCount: cells.length };
  }

  function normalizeFeature(feature, sector) {
    const properties = feature && feature.properties;
    const geometry = feature && feature.geometry;
    const parsed = properties && G.parsePracticalCode(properties.cell_id);
    if (!parsed || parsed.sector !== sector || properties.sector_id !== sector ||
        !geometry || geometry.type !== "Polygon") {
      throw new Error(`Review sector ${sector} contains an invalid practical cell.`);
    }
    const count = properties.review_count;
    if (!["muted", "undiscovered"].includes(properties.classification) ||
        !Number.isInteger(count) || count <= 0 || !Array.isArray(properties.review_ids) ||
        !Array.isArray(properties.building_ids) || properties.review_ids.length !== count ||
        properties.building_ids.length !== count) {
      throw new Error(`Review cell ${properties.cell_id} has inconsistent trigger identities.`);
    }
    return {
      cellId: properties.cell_id,
      sector,
      inspectionRow: parsed.inspectionRow,
      inspectionCol: parsed.inspectionCol,
      row: parsed.row,
      col: parsed.col,
      index: G.practicalIndex(parsed.inspectionRow, parsed.inspectionCol, parsed.row, parsed.col),
      classification: properties.classification,
      reviewCount: count,
      reviewIds: properties.review_ids.slice(),
      buildingIds: properties.building_ids.slice(),
      firstDetectedAt: properties.first_detected_at
    };
  }

  async function fetchJson(url, expected = null) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status} while loading ${url}`);
    const raw = await response.arrayBuffer();
    if (expected && raw.byteLength !== expected.byte_length) throw new Error(`Byte length mismatch for ${url}`);
    if (expected) {
      if (!global.crypto || !global.crypto.subtle) throw new Error("Web Crypto is required to verify review files.");
      const digest = await global.crypto.subtle.digest("SHA-256", raw);
      if (hex(digest) !== expected.sha256) throw new Error(`SHA-256 mismatch for ${url}`);
    }
    try {
      return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    } catch (error) {
      throw new Error(`Invalid UTF-8 JSON at ${url}: ${error.message}`);
    }
  }

  function hex(buffer) {
    return Array.from(new Uint8Array(buffer), (value) => value.toString(16).padStart(2, "0")).join("");
  }

  function join(root, path) {
    return `${stripSlash(root)}/${String(path).replace(/^\/+/, "")}`;
  }

  function stripSlash(value) {
    return String(value || "").replace(/\/+$/, "");
  }

  function unique(values) {
    return Array.from(new Set(values));
  }

  function emptySectorData() {
    return { sector: null, cells: [], reviewCount: 0, cellCount: 0 };
  }

  CFM.createReviewBundleLoader = createReviewBundleLoader;
})(window);
