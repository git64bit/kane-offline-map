(function attachRenderer(global) {
  "use strict";

  const CFM = global.CountyFieldMap;
  const K = CFM.constants;
  const G = CFM.grid;
  const COLORS = K.COLORS;
  const ANGLE = -18 * Math.PI / 180;

  function createRenderer(canvas, stateStore) {
    const context = canvas.getContext("2d", { alpha: false });
    const baseCanvas = document.createElement("canvas");
    const baseContext = baseCanvas.getContext("2d", { alpha: false });
    const viewport = createViewport(canvas);
    let boundary = [];
    let sectorData = { roads: [], water: [], buildings: [] };
    let level = "county";
    let selectedSector = null;
    let selectedInspection = null;
    let selectedPractical = null;
    let clickHandler = null;
    let rebuildQueued = false;

    function setBoundary(nextBoundary) {
      boundary = Array.isArray(nextBoundary) ? nextBoundary : [];
      viewport.fit(K.WORLD, 36);
      resizeAndRebuild();
    }

    function showCounty() {
      level = "county";
      selectedSector = null;
      selectedInspection = null;
      selectedPractical = null;
      sectorData = { roads: [], water: [], buildings: [] };
      viewport.fit(K.WORLD, 36);
      rebuildBase();
    }

    function showSector(sector) {
      level = "sector";
      selectedSector = sector;
      selectedInspection = null;
      selectedPractical = null;
      viewport.fit(G.sectorBounds(sector), 48);
      rebuildBase();
    }

    function showPractical(sector, inspection, data) {
      level = "practical";
      selectedSector = sector;
      selectedInspection = { row: inspection.row, col: inspection.col };
      selectedPractical = null;
      sectorData = data || { roads: [], water: [], buildings: [] };
      viewport.fit(G.inspectionBounds(sector, inspection.row, inspection.col), 54);
      rebuildBase();
    }

    function setSelectedPractical(cell) {
      selectedPractical = cell ? { index: cell.index, row: cell.row, col: cell.col } : null;
      renderOverlay();
    }

    function refreshState() {
      renderOverlay();
    }

    function zoom(factor) {
      viewport.zoom(factor);
      queueRebuild();
    }

    function resetView() {
      if (level === "practical") {
        viewport.fit(G.inspectionBounds(selectedSector, selectedInspection.row, selectedInspection.col), 54);
      } else if (level === "sector") {
        viewport.fit(G.sectorBounds(selectedSector), 48);
      } else {
        viewport.fit(K.WORLD, 36);
      }
      rebuildBase();
    }

    function resizeAndRebuild() {
      viewport.resize();
      baseCanvas.width = canvas.width;
      baseCanvas.height = canvas.height;
      rebuildBase();
    }

    function queueRebuild() {
      if (rebuildQueued) return;
      rebuildQueued = true;
      requestAnimationFrame(() => {
        rebuildQueued = false;
        rebuildBase();
      });
    }

    function rebuildBase() {
      if (!canvas.width || !canvas.height) return;
      resetCanvas(baseContext);
      baseContext.fillStyle = COLORS.background;
      baseContext.fillRect(0, 0, baseCanvas.width, baseCanvas.height);
      applyWorldTransform(baseContext, viewport);
      drawCountyBoundary(baseContext);
      if (level === "county") drawCountyGrid(baseContext);
      else if (level === "sector") drawInspectionGrid(baseContext);
      else drawPracticalBase(baseContext);
      renderOverlay();
    }

    function renderOverlay() {
      if (!canvas.width || !canvas.height) return;
      resetCanvas(context);
      context.drawImage(baseCanvas, 0, 0);
      applyWorldTransform(context, viewport);
      if (level === "county") drawCountyCompletion(context);
      else if (level === "sector") drawInspectionCompletion(context);
      else drawPracticalStates(context);
    }

    function drawCountyBoundary(ctx) {
      ctx.fillStyle = "rgba(255,255,255,0.025)";
      ctx.strokeStyle = COLORS.county;
      ctx.lineWidth = viewport.worldLineWidth(2.2);
      boundary.forEach((item) => drawPolygon(ctx, item.polygon, true, true));
    }

    function drawCountyGrid(ctx) {
      G.sectorCodes.forEach((sector) => {
        const bounds = G.sectorBounds(sector);
        fillRect(ctx, bounds, COLORS.undiscovered);
        strokeRect(ctx, bounds, COLORS.gridStrong, 1.6);
        drawLabel(ctx, sector, center(bounds), 17);
      });
    }

    function drawInspectionGrid(ctx) {
      const sectorBounds = G.sectorBounds(selectedSector);
      fillRect(ctx, sectorBounds, COLORS.undiscovered);
      strokeRect(ctx, sectorBounds, COLORS.gridStrong, 2.2);
      drawGridLines(ctx, sectorBounds, 16, 16, COLORS.grid, 0.8);
      drawLabel(ctx, selectedSector, [sectorBounds.minX + 14, sectorBounds.minY + 22], 15, "left");
    }

    function drawPracticalBase(ctx) {
      const bounds = G.inspectionBounds(selectedSector, selectedInspection.row, selectedInspection.col);
      ctx.save();
      pathRect(ctx, bounds);
      ctx.clip();
      drawAreas(ctx, sectorData.water, bounds, COLORS.water, "rgba(58,104,160,0.9)", 0.8);
      drawRoads(ctx, sectorData.roads, bounds);
      drawAreas(ctx, sectorData.buildings, bounds, COLORS.building, COLORS.buildingStroke, 0.75);
      ctx.restore();
      drawGridLines(ctx, bounds, 8, 8, COLORS.gridStrong, 1.0);
      strokeRect(ctx, bounds, COLORS.gridStrong, 2.4);
    }

    function drawCountyCompletion(ctx) {
      G.sectorCodes.forEach((sector) => {
        if (!stateStore.sectorComplete(sector)) return;
        fillRect(ctx, G.sectorBounds(sector), COLORS.complete);
        strokeRect(ctx, G.sectorBounds(sector), COLORS.discoveredStroke, 2.2);
      });
    }

    function drawInspectionCompletion(ctx) {
      for (let row = 0; row < 16; row += 1) {
        for (let col = 0; col < 16; col += 1) {
          if (!stateStore.inspectionComplete(selectedSector, row, col)) continue;
          const bounds = G.inspectionBounds(selectedSector, row, col);
          fillRect(ctx, bounds, COLORS.complete);
          strokeRect(ctx, bounds, COLORS.discoveredStroke, 1.2);
        }
      }
    }

    function drawPracticalStates(ctx) {
      for (let row = 0; row < 8; row += 1) {
        for (let col = 0; col < 8; col += 1) {
          const index = G.practicalIndex(selectedInspection.row, selectedInspection.col, row, col);
          const state = stateStore.getState(selectedSector, index);
          const bounds = G.practicalBounds(selectedSector, selectedInspection.row, selectedInspection.col, row, col);
          if (state === K.STATE.MUTED) fillRect(ctx, bounds, COLORS.muted);
          else if (state === K.STATE.DISCOVERED) {
            fillRect(ctx, bounds, COLORS.discovered);
            strokeRect(ctx, bounds, COLORS.discoveredStroke, 1.0);
          } else {
            fillRect(ctx, bounds, COLORS.undiscovered);
          }
        }
      }
      const parentBounds = G.inspectionBounds(selectedSector, selectedInspection.row, selectedInspection.col);
      drawGridLines(ctx, parentBounds, 8, 8, COLORS.gridStrong, 1.0);
      strokeRect(ctx, parentBounds, COLORS.gridStrong, 2.4);
      if (selectedPractical) {
        const bounds = G.practicalBounds(selectedSector, selectedInspection.row, selectedInspection.col,
          selectedPractical.row, selectedPractical.col);
        strokeRect(ctx, bounds, COLORS.selected, 3.0);
      }
    }

    function drawAreas(ctx, features, clipBounds, fill, stroke, width) {
      ctx.fillStyle = fill;
      ctx.strokeStyle = stroke;
      ctx.lineWidth = viewport.worldLineWidth(width);
      features.forEach((feature) => {
        if (!G.intersects(feature.bounds, clipBounds)) return;
        drawPolygon(ctx, feature.polygon, true, true);
      });
    }

    function drawRoads(ctx, roads, clipBounds) {
      ctx.strokeStyle = COLORS.road;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      roads.forEach((road) => {
        if (!G.intersects(road.bounds, clipBounds) || road.path.length < 2) return;
        ctx.lineWidth = viewport.worldLineWidth(Math.max(1.2, road.width * 0.34));
        ctx.beginPath();
        ctx.moveTo(road.path[0][0], road.path[0][1]);
        for (let index = 1; index < road.path.length; index += 1) ctx.lineTo(road.path[index][0], road.path[index][1]);
        ctx.stroke();
      });
    }

    function drawGridLines(ctx, bounds, rows, cols, color, width) {
      ctx.strokeStyle = color;
      ctx.lineWidth = viewport.worldLineWidth(width);
      ctx.beginPath();
      for (let col = 1; col < cols; col += 1) {
        const x = bounds.minX + (bounds.maxX - bounds.minX) * col / cols;
        ctx.moveTo(x, bounds.minY);
        ctx.lineTo(x, bounds.maxY);
      }
      for (let row = 1; row < rows; row += 1) {
        const y = bounds.minY + (bounds.maxY - bounds.minY) * row / rows;
        ctx.moveTo(bounds.minX, y);
        ctx.lineTo(bounds.maxX, y);
      }
      ctx.stroke();
    }

    function drawLabel(ctx, text, point, size, align = "center") {
      ctx.save();
      ctx.translate(point[0], point[1]);
      ctx.rotate(-ANGLE);
      ctx.scale(1 / viewport.scale(), 1 / viewport.scale());
      ctx.fillStyle = COLORS.label;
      ctx.font = `600 ${size}px system-ui, sans-serif`;
      ctx.textAlign = align;
      ctx.textBaseline = "middle";
      ctx.fillText(text, 0, 0);
      ctx.restore();
    }

    function bindPointerEvents(onClick) {
      clickHandler = onClick;
      let pointerId = null;
      let last = null;
      let start = null;
      let moved = false;
      let clickModifiers = null;
      canvas.addEventListener("pointerdown", (event) => {
        pointerId = event.pointerId;
        last = [event.clientX, event.clientY];
        start = last.slice();
        moved = false;
        clickModifiers = { shiftKey: event.shiftKey === true };
        canvas.setPointerCapture(pointerId);
      });
      canvas.addEventListener("pointermove", (event) => {
        if (event.pointerId !== pointerId || !last) return;
        const next = [event.clientX, event.clientY];
        const dx = next[0] - last[0];
        const dy = next[1] - last[1];
        if (Math.hypot(next[0] - start[0], next[1] - start[1]) > 5) moved = true;
        if (moved) {
          viewport.pan(dx, dy);
          queueRebuild();
        }
        last = next;
      });
      canvas.addEventListener("pointerup", (event) => {
        if (event.pointerId !== pointerId) return;
        canvas.releasePointerCapture(pointerId);
        if (!moved && clickHandler) {
          clickHandler(viewport.screenToWorld(event.clientX, event.clientY), {
            shiftKey: event.shiftKey === true || Boolean(clickModifiers && clickModifiers.shiftKey)
          });
        }
        pointerId = null;
        last = null;
        start = null;
        clickModifiers = null;
      });
      canvas.addEventListener("pointercancel", () => {
        pointerId = null;
        last = null;
        start = null;
        clickModifiers = null;
      });
    }

    new ResizeObserver(resizeAndRebuild).observe(canvas);
    viewport.resize();
    baseCanvas.width = canvas.width;
    baseCanvas.height = canvas.height;

    return {
      setBoundary,
      showCounty,
      showSector,
      showPractical,
      setSelectedPractical,
      refreshState,
      zoom,
      resetView,
      bindPointerEvents,
      level: () => level,
      selectedSector: () => selectedSector,
      selectedInspection: () => selectedInspection
    };
  }

  function createViewport(canvas) {
    let centerX = 700;
    let centerY = 450;
    let currentScale = 1;
    let offsetX = 0;
    let offsetY = 0;
    let cssWidth = 1;
    let cssHeight = 1;
    let dpr = 1;

    function resize() {
      const rect = canvas.getBoundingClientRect();
      cssWidth = Math.max(1, rect.width);
      cssHeight = Math.max(1, rect.height);
      dpr = Math.max(1, global.devicePixelRatio || 1);
      canvas.width = Math.round(cssWidth * dpr);
      canvas.height = Math.round(cssHeight * dpr);
    }

    function fit(bounds, padding) {
      centerX = (bounds.minX + bounds.maxX) / 2;
      centerY = (bounds.minY + bounds.maxY) / 2;
      offsetX = 0;
      offsetY = 0;
      const width = bounds.maxX - bounds.minX;
      const height = bounds.maxY - bounds.minY;
      const rotatedWidth = Math.abs(Math.cos(ANGLE)) * width + Math.abs(Math.sin(ANGLE)) * height;
      const rotatedHeight = Math.abs(Math.sin(ANGLE)) * width + Math.abs(Math.cos(ANGLE)) * height;
      currentScale = Math.min((cssWidth - padding * 2) / rotatedWidth, (cssHeight - padding * 2) / rotatedHeight);
      currentScale = Math.max(0.01, currentScale);
    }

    function pan(dx, dy) {
      offsetX += dx;
      offsetY += dy;
    }

    function zoom(factor) {
      currentScale = Math.max(0.05, Math.min(200, currentScale * factor));
    }

    function screenToWorld(clientX, clientY) {
      const rect = canvas.getBoundingClientRect();
      const sx = clientX - rect.left - cssWidth / 2 - offsetX;
      const sy = clientY - rect.top - cssHeight / 2 - offsetY;
      const dx = (sx * Math.cos(ANGLE) + sy * Math.sin(ANGLE)) / currentScale;
      const dy = (-sx * Math.sin(ANGLE) + sy * Math.cos(ANGLE)) / currentScale;
      return [centerX + dx, centerY + dy];
    }

    return {
      resize,
      fit,
      pan,
      zoom,
      screenToWorld,
      scale: () => currentScale,
      dpr: () => dpr,
      cssWidth: () => cssWidth,
      cssHeight: () => cssHeight,
      center: () => [centerX, centerY],
      offset: () => [offsetX, offsetY],
      worldLineWidth: (pixels) => pixels / currentScale
    };
  }

  function applyWorldTransform(ctx, viewport) {
    const scale = viewport.scale() * viewport.dpr();
    const cos = Math.cos(ANGLE);
    const sin = Math.sin(ANGLE);
    const center = viewport.center();
    const offset = viewport.offset();
    const e = (viewport.cssWidth() / 2 + offset[0]) * viewport.dpr() -
      scale * (cos * center[0] - sin * center[1]);
    const f = (viewport.cssHeight() / 2 + offset[1]) * viewport.dpr() -
      scale * (sin * center[0] + cos * center[1]);
    ctx.setTransform(scale * cos, scale * sin, -scale * sin, scale * cos, e, f);
  }

  function resetCanvas(ctx) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  }

  function drawPolygon(ctx, polygon, fill, stroke) {
    if (!polygon.length) return;
    ctx.beginPath();
    ctx.moveTo(polygon[0][0], polygon[0][1]);
    for (let index = 1; index < polygon.length; index += 1) ctx.lineTo(polygon[index][0], polygon[index][1]);
    ctx.closePath();
    if (fill) ctx.fill();
    if (stroke) ctx.stroke();
  }

  function pathRect(ctx, bounds) {
    ctx.beginPath();
    ctx.rect(bounds.minX, bounds.minY, bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
  }

  function fillRect(ctx, bounds, color) {
    ctx.fillStyle = color;
    ctx.fillRect(bounds.minX, bounds.minY, bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
  }

  function strokeRect(ctx, bounds, color, width) {
    ctx.strokeStyle = color;
    ctx.lineWidth = width / Math.max(0.01, Math.sqrt(Math.abs(ctx.getTransform().a ** 2 + ctx.getTransform().b ** 2)) / (global.devicePixelRatio || 1));
    ctx.strokeRect(bounds.minX, bounds.minY, bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
  }

  function center(bounds) {
    return [(bounds.minX + bounds.maxX) / 2, (bounds.minY + bounds.maxY) / 2];
  }

  CFM.createRenderer = createRenderer;
})(window);
