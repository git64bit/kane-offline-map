(function attachReviewOverlay(global) {
  "use strict";

  const CFM = global.CountyFieldMap;
  const G = CFM.grid;
  const COLORS = CFM.constants.COLORS;

  function createReviewOverlay(viewport) {
    let registry = new Map();
    let sectorData = emptySectorData();

    function setIndex(info) {
      registry = new Map(((info && info.sectors) || []).map((item) => [item.sector_id, item]));
    }

    function setSector(data) {
      sectorData = data && Array.isArray(data.cells) ? data : emptySectorData();
    }

    function clearSector() {
      sectorData = emptySectorData();
    }

    function drawCounty(ctx) {
      const maxCount = Math.max(1, ...Array.from(registry.values(), (item) => item.review_cell_count));
      registry.forEach((item, sector) => {
        if (!item.review_cell_count) return;
        const alpha = 0.06 + 0.3 * Math.sqrt(item.review_cell_count / maxCount);
        drawBounds(ctx, G.sectorBounds(sector), reviewFill(alpha), COLORS.reviewStroke, 2.4);
      });
    }

    function drawSector(ctx, sector) {
      if (sectorData.sector !== sector) return;
      groupedInspections(sectorData.cells).forEach((count, key) => {
        const [row, col] = key.split(":").map(Number);
        const alpha = Math.min(0.5, 0.16 + count * 0.018);
        drawBounds(ctx, G.inspectionBounds(sector, row, col), reviewFill(alpha), COLORS.reviewStroke, 2.0);
      });
    }

    function drawPractical(ctx, sector, inspection) {
      if (sectorData.sector !== sector || !inspection) return;
      sectorData.cells.forEach((cell) => {
        if (cell.inspectionRow !== inspection.row || cell.inspectionCol !== inspection.col) return;
        const alpha = Math.min(0.62, 0.22 + cell.reviewCount * 0.035);
        const bounds = G.practicalBounds(sector, inspection.row, inspection.col, cell.row, cell.col);
        drawBounds(ctx, bounds, reviewFill(alpha), COLORS.reviewStroke, 2.3);
      });
    }

    function groupedInspections(cells) {
      const output = new Map();
      cells.forEach((cell) => {
        const key = `${cell.inspectionRow}:${cell.inspectionCol}`;
        output.set(key, (output.get(key) || 0) + 1);
      });
      return output;
    }

    function drawBounds(ctx, bounds, fill, stroke, width) {
      if (!bounds) return;
      ctx.fillStyle = fill;
      ctx.fillRect(bounds.minX, bounds.minY, bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
      ctx.strokeStyle = stroke;
      ctx.lineWidth = viewport.worldLineWidth(width);
      ctx.strokeRect(bounds.minX, bounds.minY, bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
    }

    function reviewFill(alpha) {
      return `rgba(249,115,22,${alpha})`;
    }

    return { setIndex, setSector, clearSector, drawCounty, drawSector, drawPractical };
  }

  function emptySectorData() {
    return { sector: null, cells: [], reviewCount: 0, cellCount: 0 };
  }

  CFM.createReviewOverlay = createReviewOverlay;
})(window);
