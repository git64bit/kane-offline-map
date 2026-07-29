(function attachConstants(global) {
  "use strict";

  const CFM = global.CountyFieldMap = global.CountyFieldMap || {};

  CFM.constants = Object.freeze({
    APP_NAME: "County Field Map",
    COUNTY_NAME: "Kane County, Illinois",
    FORMAT: "county-field-map-sector-state",
    VERSION: 1,
    API_ROOT: "/__county_field_map/sector-state",
    LEGACY_API_ROOT: "/__kane_map/sector-state",
    STORAGE_PATH: "project-data/sectors",
    LOCAL_PREFIX: "county-field-map.sector.v1.",
    WORLD: Object.freeze({ minX: 0, minY: 0, maxX: 1400, maxY: 900 }),
    REFERENCE_GRID: Object.freeze({ rows: 4, cols: 6, startNorth: 11, startEast: 5 }),
    VALID_GRID: Object.freeze({ northMin: 11, northMax: 14, eastMin: 6, eastMax: 9 }),
    INSPECTION_SIZE: 16,
    PRACTICAL_SIZE: 8,
    PRACTICAL_PER_INSPECTION: 64,
    PRACTICAL_PER_SECTOR: 16384,
    STATE: Object.freeze({ UNDISCOVERED: 0, DISCOVERED: 1, MUTED: 2 }),
    COLORS: Object.freeze({
      background: "#111827",
      panel: "#f7f7f5",
      county: "#d7dde5",
      grid: "rgba(255,255,255,0.48)",
      gridStrong: "rgba(255,255,255,0.92)",
      label: "#f8fafc",
      water: "rgba(79,142,210,0.72)",
      road: "rgba(215,161,83,0.86)",
      building: "rgba(215,161,83,0.86)",
      buildingStroke: "rgba(97,64,24,0.9)",
      undiscovered: "rgba(150,158,170,0.17)",
      discovered: "rgba(24,185,103,0.25)",
      discoveredStroke: "rgba(20,150,82,0.95)",
      muted: "rgba(0,0,0,0.985)",
      selected: "#fde047",
      complete: "rgba(22,163,74,0.42)"
    })
  });
})(window);
