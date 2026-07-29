(function bootCountyFieldMap(global) {
  "use strict";

  const CFM = global.CountyFieldMap;
  const K = CFM.constants;
  const G = CFM.grid;

  const elements = {
    canvas: document.getElementById("mapCanvas"),
    countyView: document.getElementById("countyView"),
    backView: document.getElementById("backView"),
    zoomIn: document.getElementById("zoomIn"),
    zoomOut: document.getElementById("zoomOut"),
    resetView: document.getElementById("resetView"),
    muteSelected: document.getElementById("muteSelected"),
    returnUndiscovered: document.getElementById("returnUndiscovered"),
    muteInspection: document.getElementById("muteInspection"),
    levelStatus: document.getElementById("levelStatus"),
    selectionStatus: document.getElementById("selectionStatus"),
    sectorProgress: document.getElementById("sectorProgress"),
    inspectionProgress: document.getElementById("inspectionProgress"),
    storageStatus: document.getElementById("storageStatus"),
    loading: document.getElementById("loadingMessage"),
    fatal: document.getElementById("fatalError")
  };

  let store;
  let loader;
  let renderer;
  let selectedPractical = null;
  let transitionToken = 0;

  function requireElements() {
    Object.entries(elements).forEach(([name, element]) => {
      if (!element) throw new Error(`Required interface element is missing: ${name}`);
    });
  }

  async function start() {
    requireElements();
    store = CFM.createStateStore();
    loader = CFM.createDataLoader();
    renderer = CFM.createRenderer(elements.canvas, store);
    bindEvents();
    bindStore();
    setLoading("Loading county boundary…");
    const loaded = await loader.loadBoundary();
    renderer.setBoundary(loaded.boundary);
    renderer.showCounty();
    setLoading("");
    updateUi();
    store.connect().catch((error) => {
      console.error("County Field Map storage connection failed", error);
      setStorageStatus("local", `Browser journal active; ${error.message}`);
    });
  }

  function bindEvents() {
    renderer.bindPointerEvents(handleMapClick);
    elements.countyView.addEventListener("click", () => showCounty());
    elements.backView.addEventListener("click", () => goBack());
    elements.zoomIn.addEventListener("click", () => renderer.zoom(1.25));
    elements.zoomOut.addEventListener("click", () => renderer.zoom(0.8));
    elements.resetView.addEventListener("click", () => renderer.resetView());
    elements.muteSelected.addEventListener("click", () => classifySelected(K.STATE.MUTED));
    elements.returnUndiscovered.addEventListener("click", () => classifySelected(K.STATE.UNDISCOVERED));
    elements.muteInspection.addEventListener("click", () => muteCurrentInspection());
    global.addEventListener("beforeunload", () => store.flush());
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") store.flush();
    });
  }

  function bindStore() {
    store.onChange(({ sector }) => {
      if (!renderer || (sector && sector !== renderer.selectedSector())) return;
      renderer.refreshState();
      updateUi();
    });
    store.onStatus(({ kind, message }) => setStorageStatus(kind, message));
  }

  async function handleMapClick(point, modifiers = {}) {
    const level = renderer.level();
    if (level === "county") {
      const sector = G.pointToSector(point);
      if (sector) await showSector(sector.code);
      return;
    }
    if (level === "sector") {
      const sector = renderer.selectedSector();
      const inspection = G.pointToInspection(point, sector);
      if (inspection) await showPractical(sector, inspection);
      return;
    }
    const inspection = renderer.selectedInspection();
    const sector = renderer.selectedSector();
    const practical = G.pointToPractical(point, sector, inspection.row, inspection.col);
    if (!practical) return;
    selectedPractical = practical;
    const nextState = modifiers.shiftKey ? K.STATE.MUTED : K.STATE.DISCOVERED;
    store.setState(sector, practical.index, nextState);
    renderer.setSelectedPractical(practical);
    updateUi();
  }

  async function showSector(sector) {
    const current = renderer.selectedSector();
    if (current && current !== sector) await store.flush(current);
    transitionToken += 1;
    selectedPractical = null;
    loader.releaseSector();
    renderer.showSector(sector);
    updateUi();
  }

  async function showPractical(sector, inspection) {
    const token = ++transitionToken;
    selectedPractical = null;
    setLoading(`Loading roads, water and buildings for ${sector}…`);
    updateUi();
    try {
      const data = await loader.loadSector(sector);
      if (token !== transitionToken) return;
      store.discoverUndiscoveredInspection(sector, inspection.row, inspection.col);
      renderer.showPractical(sector, inspection, data);
    } catch (error) {
      console.error("County Field Map sector load failed", error);
      showFatal(`The field data for ${sector} could not be loaded. ${error.message}`);
    } finally {
      if (token === transitionToken) {
        setLoading("");
        updateUi();
      }
    }
  }

  function showCounty() {
    transitionToken += 1;
    const sector = renderer.selectedSector();
    if (sector) store.flush(sector);
    selectedPractical = null;
    loader.releaseSector();
    renderer.showCounty();
    updateUi();
  }

  function goBack() {
    if (renderer.level() === "practical") {
      const sector = renderer.selectedSector();
      selectedPractical = null;
      renderer.showSector(sector);
      updateUi();
    } else if (renderer.level() === "sector") {
      showCounty();
    }
  }

  function classifySelected(state) {
    if (!selectedPractical || renderer.level() !== "practical") return;
    store.setState(selectedPractical.sector, selectedPractical.index, state);
    renderer.setSelectedPractical(selectedPractical);
    updateUi();
  }

  function muteCurrentInspection() {
    if (renderer.level() !== "practical") return;
    const sector = renderer.selectedSector();
    const inspection = renderer.selectedInspection();
    if (!sector || !inspection) return;
    const confirmed = global.confirm(
      "Mute all 64 practical cells in this 8 × 8 grid? This replaces discovered cells with muted voids."
    );
    if (!confirmed) return;
    store.setInspectionState(sector, inspection.row, inspection.col, K.STATE.MUTED);
  }

  function updateUi() {
    if (!renderer) return;
    const level = renderer.level();
    const sector = renderer.selectedSector();
    const inspection = renderer.selectedInspection();
    elements.countyView.disabled = level === "county";
    elements.backView.disabled = level === "county";
    elements.muteSelected.disabled = !selectedPractical || level !== "practical";
    elements.returnUndiscovered.disabled = !selectedPractical || level !== "practical";
    elements.muteInspection.disabled = level !== "practical";

    if (level === "county") {
      elements.levelStatus.textContent = "County — select one of the 16 sectors";
      elements.selectionStatus.textContent = "No practical cell selected";
      elements.sectorProgress.textContent = countyProgressText();
      elements.inspectionProgress.textContent = "Select a sector to continue.";
      return;
    }

    const summary = store.summary(sector);
    elements.sectorProgress.textContent = `${sector}: ${formatNumber(summary.classified)} of ${formatNumber(K.PRACTICAL_PER_SECTOR)} practical cells classified; ${summary.completeInspections} of 256 inspection cells complete.`;
    if (level === "sector") {
      elements.levelStatus.textContent = `${sector} — select a 16 × 16 inspection cell`;
      elements.selectionStatus.textContent = "No practical cell selected";
      elements.inspectionProgress.textContent = "Green inspection cells are complete. Gray cells still contain undiscovered practical cells.";
      return;
    }

    const detail = store.inspectionSummary(sector, inspection.row, inspection.col);
    elements.levelStatus.textContent = `${sector} / inspection ${inspection.row + 1}-${inspection.col + 1}`;
    elements.inspectionProgress.textContent = `${detail.classified} of 64 practical cells classified; ${detail.remaining} undiscovered.`;
    elements.selectionStatus.textContent = selectedPractical
      ? selectedText(selectedPractical)
      : "Practical cells load included/green; Shift-click or use Mute selected sector to make a cell black.";
  }

  function countyProgressText() {
    let complete = 0;
    let classified = 0;
    G.sectorCodes.forEach((sector) => {
      const summary = store.summary(sector);
      classified += summary.classified;
      if (store.sectorComplete(sector)) complete += 1;
    });
    return `${complete} of 16 sectors complete; ${formatNumber(classified)} practical cells classified county-wide.`;
  }

  function selectedText(cell) {
    const state = store.getState(cell.sector, cell.index);
    const label = state === K.STATE.MUTED ? "muted" : state === K.STATE.DISCOVERED ? "discovered" : "undiscovered";
    return `Selected practical cell ${cell.row + 1}-${cell.col + 1}: ${label}.`;
  }

  function formatNumber(value) {
    return Number(value).toLocaleString("en-US");
  }

  function setLoading(message) {
    elements.loading.textContent = message;
    elements.loading.hidden = !message;
  }

  function setStorageStatus(kind, message) {
    elements.storageStatus.dataset.kind = kind || "local";
    elements.storageStatus.textContent = message;
  }

  function showFatal(message) {
    elements.fatal.textContent = message;
    elements.fatal.hidden = false;
  }

  start().catch((error) => {
    console.error("County Field Map boot failed", error);
    if (elements.fatal) showFatal(error.message || String(error));
    if (elements.loading) setLoading("");
  });
})(window);
