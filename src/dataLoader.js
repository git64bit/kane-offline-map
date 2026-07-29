(function attachDataLoader(global) {
  "use strict";

  const CFM = global.CountyFieldMap;
  const K = CFM.constants;
  const G = CFM.grid;

  function createDataLoader(options = {}) {
    const configured = global.CountyFieldMapConfig || {};
    const query = new URLSearchParams(global.location.search || "");
    const explicitRoot = query.get("bundle") || query.get("bundleRoot") || query.get("bundle-root");
    const roots = unique([
      explicitRoot,
      options.bundlePath,
      configured.bundlePath,
      "data/kane-county",
      "data",
      "prepared",
      "processing/output/prepared"
    ].filter(Boolean));
    let bundleRoot = null;
    let projection = null;
    let boundary = [];
    let loadedSector = null;
    let sectorData = emptySectorData();
    let loadGeneration = 0;

    async function loadBoundary() {
      let lastError = null;
      for (const root of roots) {
        try {
          const collection = await fetchJson(join(root, "county_boundary.json"));
          const features = featureArray(collection);
          const rawBounds = boundsForFeatures(features);
          if (!completeBounds(rawBounds)) throw new Error("County boundary contains no usable coordinates.");
          projection = createProjection(rawBounds, K.WORLD, 35);
          boundary = features.flatMap((feature, index) =>
            polygonRings(feature.geometry).map((ring, ringIndex) => ({
              id: String(feature.id || `county-${index + 1}-${ringIndex + 1}`),
              polygon: ring.map(projectPoint)
            }))
          ).filter((item) => item.polygon.length >= 3);
          if (!boundary.length) throw new Error("County boundary contains no polygon geometry.");
          bundleRoot = stripSlash(root);
          return { bundleRoot, boundary, projection };
        } catch (error) {
          lastError = error;
          if (explicitRoot) break;
        }
      }
      throw new Error(`Prepared county data could not be loaded. ${lastError ? lastError.message : "No bundle path succeeded."}`);
    }

    async function loadSector(sector) {
      if (!projection || !bundleRoot) throw new Error("County boundary must load before sector data.");
      if (!G.parseSector(sector)) throw new Error(`Invalid sector ${sector}.`);
      if (loadedSector === sector) return sectorData;
      const generation = ++loadGeneration;
      const rawSectorBounds = rawBoundsForWorldBounds(G.sectorBounds(sector));
      const [roadsJson, waterJson, buildingsJson] = await Promise.all([
        fetchJson(join(bundleRoot, "roads.json")),
        fetchJson(join(bundleRoot, "water.json")),
        fetchJson(join(bundleRoot, "buildings.json"))
      ]);
      const nextData = {
        sector,
        roads: convertRoads(featureArray(roadsJson), rawSectorBounds),
        water: convertAreas(featureArray(waterJson), rawSectorBounds, "water"),
        buildings: convertAreas(featureArray(buildingsJson), rawSectorBounds, "building")
      };
      if (generation === loadGeneration) {
        sectorData = nextData;
        loadedSector = sector;
      }
      return nextData;
    }

    function releaseSector() {
      loadGeneration += 1;
      loadedSector = null;
      sectorData = emptySectorData();
    }

    function convertRoads(features, wantedBounds) {
      const output = [];
      features.forEach((feature, featureIndex) => {
        const rawBounds = boundsForFeature(feature);
        if (!completeBounds(rawBounds) || !boundsIntersect(rawBounds, wantedBounds)) return;
        linePaths(feature.geometry).forEach((path, pathIndex) => {
          const projected = path.map(projectPoint).filter(validPoint);
          if (projected.length < 2) return;
          const props = feature.properties || {};
          output.push({
            id: String(feature.id || props.id || `road-${featureIndex + 1}-${pathIndex + 1}`),
            width: roadWidth(props),
            path: projected,
            bounds: boundsForPoints(projected)
          });
        });
      });
      return output;
    }

    function convertAreas(features, wantedBounds, kind) {
      const output = [];
      features.forEach((feature, featureIndex) => {
        const rawBounds = boundsForFeature(feature);
        if (!completeBounds(rawBounds) || !boundsIntersect(rawBounds, wantedBounds)) return;
        polygonRings(feature.geometry).forEach((ring, ringIndex) => {
          const polygon = ring.map(projectPoint).filter(validPoint);
          if (polygon.length < 3) return;
          output.push({
            id: String(feature.id || (feature.properties || {}).id || `${kind}-${featureIndex + 1}-${ringIndex + 1}`),
            polygon,
            bounds: boundsForPoints(polygon)
          });
        });
      });
      return output;
    }

    function projectPoint(point) {
      return [
        projection.offsetX + (Number(point[0]) - projection.rawBounds.minX) * projection.scale,
        projection.offsetY + (projection.rawBounds.maxY - Number(point[1])) * projection.scale
      ];
    }

    function unprojectPoint(point) {
      return [
        projection.rawBounds.minX + (Number(point[0]) - projection.offsetX) / projection.scale,
        projection.rawBounds.maxY - (Number(point[1]) - projection.offsetY) / projection.scale
      ];
    }

    function rawBoundsForWorldBounds(bounds) {
      const a = unprojectPoint([bounds.minX, bounds.minY]);
      const b = unprojectPoint([bounds.maxX, bounds.maxY]);
      return {
        minX: Math.min(a[0], b[0]),
        minY: Math.min(a[1], b[1]),
        maxX: Math.max(a[0], b[0]),
        maxY: Math.max(a[1], b[1])
      };
    }

    return {
      loadBoundary,
      loadSector,
      releaseSector,
      boundary: () => boundary,
      currentSector: () => loadedSector,
      bundleRoot: () => bundleRoot
    };
  }

  function createProjection(rawBounds, world, padding) {
    const rawWidth = Math.max(Number.EPSILON, rawBounds.maxX - rawBounds.minX);
    const rawHeight = Math.max(Number.EPSILON, rawBounds.maxY - rawBounds.minY);
    const targetWidth = world.maxX - world.minX - padding * 2;
    const targetHeight = world.maxY - world.minY - padding * 2;
    const scale = Math.min(targetWidth / rawWidth, targetHeight / rawHeight);
    const usedWidth = rawWidth * scale;
    const usedHeight = rawHeight * scale;
    return {
      rawBounds,
      scale,
      offsetX: world.minX + (world.maxX - world.minX - usedWidth) / 2,
      offsetY: world.minY + (world.maxY - world.minY - usedHeight) / 2
    };
  }

  function featureArray(collection) {
    if (Array.isArray(collection)) return collection;
    return collection && Array.isArray(collection.features) ? collection.features : [];
  }

  function linePaths(geometry = {}) {
    if (geometry.type === "LineString" && Array.isArray(geometry.coordinates)) return [geometry.coordinates];
    if (geometry.type === "MultiLineString" && Array.isArray(geometry.coordinates)) return geometry.coordinates;
    return [];
  }

  function polygonRings(geometry = {}) {
    if (geometry.type === "Polygon" && Array.isArray(geometry.coordinates)) {
      return geometry.coordinates.length ? [geometry.coordinates[0]] : [];
    }
    if (geometry.type === "MultiPolygon" && Array.isArray(geometry.coordinates)) {
      return geometry.coordinates.map((polygon) => Array.isArray(polygon) ? polygon[0] : null).filter(Array.isArray);
    }
    return [];
  }

  function boundsForFeatures(features) {
    const bounds = emptyBounds();
    features.forEach((feature) => walkCoordinates(feature && feature.geometry && feature.geometry.coordinates,
      (point) => expandBounds(bounds, point)));
    return bounds;
  }

  function boundsForFeature(feature) {
    const bounds = emptyBounds();
    walkCoordinates(feature && feature.geometry && feature.geometry.coordinates, (point) => expandBounds(bounds, point));
    return bounds;
  }

  function boundsForPoints(points) {
    const bounds = emptyBounds();
    points.forEach((point) => expandBounds(bounds, point));
    return bounds;
  }

  function walkCoordinates(value, callback) {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && Number.isFinite(Number(value[0])) && Number.isFinite(Number(value[1]))) {
      callback(value);
      return;
    }
    value.forEach((item) => walkCoordinates(item, callback));
  }

  function emptyBounds() {
    return { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
  }

  function expandBounds(bounds, point) {
    const x = Number(point[0]);
    const y = Number(point[1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    bounds.minX = Math.min(bounds.minX, x);
    bounds.minY = Math.min(bounds.minY, y);
    bounds.maxX = Math.max(bounds.maxX, x);
    bounds.maxY = Math.max(bounds.maxY, y);
  }

  function completeBounds(bounds) {
    return bounds && Number.isFinite(bounds.minX) && Number.isFinite(bounds.minY) &&
      Number.isFinite(bounds.maxX) && Number.isFinite(bounds.maxY);
  }

  function boundsIntersect(a, b) {
    return a.minX <= b.maxX && a.maxX >= b.minX && a.minY <= b.maxY && a.maxY >= b.minY;
  }

  function roadWidth(properties) {
    const type = String(properties.route_type || properties.mtfcc || "").toLowerCase();
    if (type.includes("interstate")) return 12;
    if (type.includes("state") || type.includes("us")) return 9;
    return 5;
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "force-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status} while loading ${url}`);
    return response.json();
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

  function validPoint(point) {
    return Array.isArray(point) && Number.isFinite(point[0]) && Number.isFinite(point[1]);
  }

  function emptySectorData() {
    return { sector: null, roads: [], water: [], buildings: [] };
  }

  CFM.createDataLoader = createDataLoader;
})(window);
