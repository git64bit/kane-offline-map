(function attachStateStore(global) {
  "use strict";

  const CFM = global.CountyFieldMap;
  const K = CFM.constants;
  const G = CFM.grid;
  const sectorSet = new Set(G.sectorCodes);

  function createStateStore() {
    const records = new Map();
    const listeners = new Set();
    const statusListeners = new Set();
    const saveTimers = new Map();
    let apiRoot = K.API_ROOT;
    let apiMode = "none";
    let writeQueue = Promise.resolve();

    G.sectorCodes.forEach((sector) => records.set(sector, loadLocalRecord(sector)));

    function requireRecord(sector) {
      if (!sectorSet.has(sector)) throw new Error(`Invalid County Field Map sector: ${sector || "unknown"}`);
      return records.get(sector);
    }

    function getState(sector, index) {
      const record = requireRecord(sector);
      return validIndex(index) ? record.cells[index] : K.STATE.UNDISCOVERED;
    }

    function setState(sector, index, nextState) {
      const record = requireRecord(sector);
      if (!validIndex(index) || !validState(nextState)) return false;
      const previous = record.cells[index];
      if (previous === nextState) return false;
      updateCounts(record, index, previous, nextState);
      record.cells[index] = nextState;
      record.updatedAt = new Date().toISOString();
      saveLocalRecord(record);
      scheduleDiskWrite(sector);
      emitChange(sector, index, previous, nextState);
      return true;
    }

    function setInspectionState(sector, row, col, nextState) {
      const record = requireRecord(sector);
      if (!Number.isInteger(row) || row < 0 || row >= 16 ||
          !Number.isInteger(col) || col < 0 || col >= 16 || !validState(nextState)) return 0;
      const start = (row * 16 + col) * K.PRACTICAL_PER_INSPECTION;
      let changed = 0;
      for (let offset = 0; offset < K.PRACTICAL_PER_INSPECTION; offset += 1) {
        const index = start + offset;
        const previous = record.cells[index];
        if (previous === nextState) continue;
        updateCounts(record, index, previous, nextState);
        record.cells[index] = nextState;
        changed += 1;
      }
      if (!changed) return 0;
      record.updatedAt = new Date().toISOString();
      saveLocalRecord(record);
      scheduleDiskWrite(sector);
      emitChange(sector, null, null, nextState);
      return changed;
    }

    function discoverUndiscoveredInspection(sector, row, col) {
      const record = requireRecord(sector);
      if (!Number.isInteger(row) || row < 0 || row >= 16 ||
          !Number.isInteger(col) || col < 0 || col >= 16) return 0;
      const start = (row * 16 + col) * K.PRACTICAL_PER_INSPECTION;
      let changed = 0;
      for (let offset = 0; offset < K.PRACTICAL_PER_INSPECTION; offset += 1) {
        const index = start + offset;
        if (record.cells[index] !== K.STATE.UNDISCOVERED) continue;
        updateCounts(record, index, K.STATE.UNDISCOVERED, K.STATE.DISCOVERED);
        record.cells[index] = K.STATE.DISCOVERED;
        changed += 1;
      }
      if (!changed) return 0;
      record.updatedAt = new Date().toISOString();
      saveLocalRecord(record);
      scheduleDiskWrite(sector);
      emitChange(sector, null, K.STATE.UNDISCOVERED, K.STATE.DISCOVERED);
      return changed;
    }

    function inspectionComplete(sector, row, col) {
      const record = requireRecord(sector);
      return record.inspectionCounts[row * 16 + col] === 64;
    }

    function sectorComplete(sector) {
      return requireRecord(sector).completeInspections === 256;
    }

    function summary(sector) {
      const record = requireRecord(sector);
      return {
        discovered: record.discovered,
        muted: record.muted,
        classified: record.discovered + record.muted,
        remaining: K.PRACTICAL_PER_SECTOR - record.discovered - record.muted,
        completeInspections: record.completeInspections,
        updatedAt: record.updatedAt
      };
    }

    function inspectionSummary(sector, row, col) {
      const record = requireRecord(sector);
      const start = (row * 16 + col) * 64;
      let discovered = 0;
      let muted = 0;
      for (let offset = 0; offset < 64; offset += 1) {
        const state = record.cells[start + offset];
        if (state === K.STATE.DISCOVERED) discovered += 1;
        else if (state === K.STATE.MUTED) muted += 1;
      }
      return { discovered, muted, classified: discovered + muted, remaining: 64 - discovered - muted };
    }

    async function connect() {
      setStatus("connecting", "Connecting classification storage…");
      let health = null;
      try {
        health = await fetchJson(K.API_ROOT);
        apiRoot = K.API_ROOT;
        apiMode = "current";
      } catch (currentError) {
        try {
          health = await fetchJson(K.LEGACY_API_ROOT);
          apiRoot = K.LEGACY_API_ROOT;
          apiMode = "legacy";
        } catch (legacyError) {
          apiMode = "none";
          setStatus("local", "Browser journal active; TrivialHTTP storage unavailable.");
          return { connected: false };
        }
      }
      if (!health || health.ok !== true || Number(health.sectorCount) !== 16) {
        apiMode = "none";
        setStatus("local", "Browser journal active; sector storage response was invalid.");
        return { connected: false };
      }
      let imported = 0;
      for (const sector of G.sectorCodes) {
        const diskDocument = await readOptionalDocument(sector);
        if (diskDocument) {
          imported += 1;
          mergeDocument(sector, diskDocument);
        }
      }
      for (const sector of G.sectorCodes) await writeSector(sector);
      setStatus("connected", `Classification storage connected (${imported} existing sector files).`);
      emitChange(null, null, null, null);
      return { connected: true, imported };
    }

    function mergeDocument(sector, document) {
      const imported = recordFromDocument(sector, document);
      const local = requireRecord(sector);
      if (timestamp(imported.updatedAt) <= timestamp(local.updatedAt)) return false;
      records.set(sector, imported);
      saveLocalRecord(imported);
      return true;
    }

    function scheduleDiskWrite(sector) {
      if (apiMode === "none") return;
      clearTimeout(saveTimers.get(sector));
      saveTimers.set(sector, setTimeout(() => {
        saveTimers.delete(sector);
        queueWrite(sector);
      }, 350));
    }

    function queueWrite(sector) {
      writeQueue = writeQueue.then(() => writeSector(sector)).catch((error) => {
        console.error("County Field Map sector save failed", error);
        setStatus("local", `Browser journal saved; disk write failed: ${error.message}`);
      });
      return writeQueue;
    }

    async function flush(sector) {
      if (sector && saveTimers.has(sector)) {
        clearTimeout(saveTimers.get(sector));
        saveTimers.delete(sector);
        queueWrite(sector);
      } else if (!sector) {
        Array.from(saveTimers.keys()).forEach((code) => {
          clearTimeout(saveTimers.get(code));
          saveTimers.delete(code);
          queueWrite(code);
        });
      }
      return writeQueue;
    }

    async function writeSector(sector) {
      if (apiMode === "none") return false;
      const record = requireRecord(sector);
      const document = apiMode === "legacy" ? legacyDocument(record) : currentDocument(record);
      const response = await fetch(`${apiRoot}/${sector}.json`, {
        method: "PUT",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: `${JSON.stringify(document)}\n`,
        cache: "no-store"
      });
      if (!response.ok) throw await responseError(response, `${sector}.json could not be written.`);
      setStatus("connected", `Saved ${sector} at ${new Date().toLocaleTimeString()}.`);
      return true;
    }

    async function readOptionalDocument(sector) {
      const response = await fetch(`${apiRoot}/${sector}.json`, { cache: "no-store" });
      if (response.status === 404) return null;
      if (!response.ok) throw await responseError(response, `${sector}.json could not be read.`);
      try {
        return await response.json();
      } catch (error) {
        throw new Error(`${sector}.json is not valid JSON.`);
      }
    }

    function onChange(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }

    function onStatus(listener) {
      statusListeners.add(listener);
      return () => statusListeners.delete(listener);
    }

    function emitChange(sector, index, previous, next) {
      listeners.forEach((listener) => listener({ sector, index, previous, next }));
    }

    function setStatus(kind, message) {
      statusListeners.forEach((listener) => listener({ kind, message }));
    }

    return {
      getState,
      setState,
      setInspectionState,
      discoverUndiscoveredInspection,
      inspectionComplete,
      sectorComplete,
      summary,
      inspectionSummary,
      connect,
      flush,
      onChange,
      onStatus,
      apiMode: () => apiMode,
      record: (sector) => requireRecord(sector)
    };
  }

  function emptyRecord(sector) {
    const record = {
      sector,
      cells: new Uint8Array(K.PRACTICAL_PER_SECTOR),
      inspectionCounts: new Uint8Array(256),
      completeInspections: 0,
      discovered: 0,
      muted: 0,
      updatedAt: null
    };
    return record;
  }

  function loadLocalRecord(sector) {
    const record = emptyRecord(sector);
    try {
      const raw = global.localStorage.getItem(K.LOCAL_PREFIX + sector);
      if (!raw) return record;
      const parsed = JSON.parse(raw);
      if (!parsed || parsed.version !== K.VERSION || parsed.sector !== sector || !parsed.packed) return record;
      const decoded = unpackStates(parsed.packed);
      if (decoded.length !== K.PRACTICAL_PER_SECTOR) return record;
      record.cells.set(decoded);
      record.updatedAt = validTimestamp(parsed.updatedAt);
      recalculate(record);
    } catch (error) {
      console.warn(`Local classification journal for ${sector} could not be loaded.`, error);
    }
    return record;
  }

  function saveLocalRecord(record) {
    try {
      global.localStorage.setItem(K.LOCAL_PREFIX + record.sector, JSON.stringify({
        format: "county-field-map-local-sector",
        version: K.VERSION,
        sector: record.sector,
        updatedAt: record.updatedAt,
        packed: packStates(record.cells)
      }));
    } catch (error) {
      console.error(`Local classification journal for ${record.sector} could not be saved.`, error);
    }
  }

  function recordFromDocument(sector, document) {
    const record = emptyRecord(sector);
    if (!document || document.sector !== sector) return record;
    if (document.format === K.FORMAT) importCurrent(record, document);
    else if (document.format === "kane-map-sector-state") importLegacy(record, document);
    record.updatedAt = validTimestamp(document.updatedAt);
    recalculate(record);
    return record;
  }

  function importCurrent(record, document) {
    const practical = document.practical || {};
    applyIndices(record, practical.discovered, K.STATE.DISCOVERED);
    applyIndices(record, practical.muted, K.STATE.MUTED);
  }

  function importLegacy(record, document) {
    const state = document.state || {};
    if (state.sector === "muted") record.cells.fill(K.STATE.MUTED);
    const inspection = state.inspection || {};
    (inspection.muted || []).forEach((code) => {
      const parsed = G.parseInspectionCode(code);
      if (!parsed || parsed.sector !== record.sector) return;
      const start = (parsed.row * 16 + parsed.col) * 64;
      record.cells.fill(K.STATE.MUTED, start, start + 64);
    });
    const practical = state.practical || {};
    applyLegacyCodes(record, practical.active, K.STATE.DISCOVERED);
    applyLegacyCodes(record, practical.muted, K.STATE.MUTED);
  }

  function applyIndices(record, values, state) {
    (Array.isArray(values) ? values : []).forEach((value) => {
      const index = Number(value);
      if (validIndex(index)) record.cells[index] = state;
    });
  }

  function applyLegacyCodes(record, values, state) {
    (Array.isArray(values) ? values : []).forEach((code) => {
      const parsed = G.parsePracticalCode(code);
      if (!parsed || parsed.sector !== record.sector) return;
      record.cells[G.practicalIndex(parsed.inspectionRow, parsed.inspectionCol, parsed.row, parsed.col)] = state;
    });
  }

  function currentDocument(record) {
    const discovered = [];
    const muted = [];
    record.cells.forEach((state, index) => {
      if (state === K.STATE.DISCOVERED) discovered.push(index);
      else if (state === K.STATE.MUTED) muted.push(index);
    });
    return {
      format: K.FORMAT,
      version: K.VERSION,
      county: K.COUNTY_NAME,
      sector: record.sector,
      updatedAt: record.updatedAt,
      grid: { inspection: [16, 16], practical: [8, 8], indexOrder: "inspection-row-major then practical-row-major" },
      practical: { discovered, muted },
      counts: { discovered: record.discovered, muted: record.muted, completeInspections: record.completeInspections }
    };
  }

  function legacyDocument(record) {
    const active = [];
    const muted = [];
    const activeInspection = [];
    const mutedInspection = [];
    for (let inspection = 0; inspection < 256; inspection += 1) {
      let activeChildren = 0;
      let mutedChildren = 0;
      for (let offset = 0; offset < 64; offset += 1) {
        const index = inspection * 64 + offset;
        const decoded = G.decodePracticalIndex(index);
        const code = G.practicalCode(record.sector, decoded.inspectionRow, decoded.inspectionCol, decoded.row, decoded.col);
        if (record.cells[index] === K.STATE.DISCOVERED) { active.push(code); activeChildren += 1; }
        else if (record.cells[index] === K.STATE.MUTED) { muted.push(code); mutedChildren += 1; }
      }
      const row = Math.floor(inspection / 16);
      const col = inspection % 16;
      if (mutedChildren === 64) mutedInspection.push(G.inspectionCode(record.sector, row, col));
      else if (activeChildren + mutedChildren > 0) activeInspection.push(G.inspectionCode(record.sector, row, col));
    }
    return {
      format: "kane-map-sector-state",
      version: 1,
      county: K.COUNTY_NAME,
      sector: record.sector,
      updatedAt: record.updatedAt,
      state: {
        sector: record.discovered + record.muted ? "active" : "undiscovered",
        inspection: { active: activeInspection, muted: mutedInspection },
        practical: { active, muted }
      }
    };
  }


  function updateCounts(record, index, previous, nextState) {
    const inspection = Math.floor(index / 64);
    const wasClassified = previous !== K.STATE.UNDISCOVERED;
    const nowClassified = nextState !== K.STATE.UNDISCOVERED;
    const previousCount = record.inspectionCounts[inspection];
    if (previous === K.STATE.DISCOVERED) record.discovered -= 1;
    else if (previous === K.STATE.MUTED) record.muted -= 1;
    if (nextState === K.STATE.DISCOVERED) record.discovered += 1;
    else if (nextState === K.STATE.MUTED) record.muted += 1;
    if (wasClassified !== nowClassified) {
      const nextCount = previousCount + (nowClassified ? 1 : -1);
      record.inspectionCounts[inspection] = nextCount;
      if (previousCount === 64 && nextCount === 63) record.completeInspections -= 1;
      else if (previousCount === 63 && nextCount === 64) record.completeInspections += 1;
    }
  }

  function recalculate(record) {
    record.inspectionCounts.fill(0);
    record.discovered = 0;
    record.muted = 0;
    record.cells.forEach((state, index) => {
      if (state === K.STATE.DISCOVERED) record.discovered += 1;
      else if (state === K.STATE.MUTED) record.muted += 1;
      if (state !== K.STATE.UNDISCOVERED) record.inspectionCounts[Math.floor(index / 64)] += 1;
    });
    record.completeInspections = 0;
    record.inspectionCounts.forEach((count) => { if (count === 64) record.completeInspections += 1; });
  }

  function packStates(states) {
    const bytes = new Uint8Array(Math.ceil(states.length / 4));
    states.forEach((state, index) => { bytes[Math.floor(index / 4)] |= (state & 3) << ((index % 4) * 2); });
    let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    return btoa(binary);
  }

  function unpackStates(packed) {
    const binary = atob(String(packed || ""));
    const output = new Uint8Array(K.PRACTICAL_PER_SECTOR);
    for (let index = 0; index < output.length; index += 1) {
      const byte = binary.charCodeAt(Math.floor(index / 4)) || 0;
      output[index] = (byte >> ((index % 4) * 2)) & 3;
    }
    return output;
  }

  function validState(state) {
    return state === K.STATE.UNDISCOVERED || state === K.STATE.DISCOVERED || state === K.STATE.MUTED;
  }

  function validIndex(index) {
    return Number.isInteger(index) && index >= 0 && index < K.PRACTICAL_PER_SECTOR;
  }

  function validTimestamp(value) {
    return value && !Number.isNaN(Date.parse(value)) ? value : null;
  }

  function timestamp(value) {
    return value ? Date.parse(value) || 0 : 0;
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw await responseError(response, "Classification storage is unavailable.");
    return response.json();
  }

  async function responseError(response, fallback) {
    try {
      const payload = await response.json();
      return new Error(payload && payload.error ? payload.error : fallback);
    } catch (error) {
      return new Error(fallback);
    }
  }

  CFM.createStateStore = createStateStore;
})(window);
