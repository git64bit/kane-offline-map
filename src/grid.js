(function attachGrid(global) {
  "use strict";

  const CFM = global.CountyFieldMap;
  const K = CFM.constants;

  function sectorCodes() {
    const output = [];
    for (let north = K.VALID_GRID.northMin; north <= K.VALID_GRID.northMax; north += 1) {
      for (let east = K.VALID_GRID.eastMin; east <= K.VALID_GRID.eastMax; east += 1) {
        output.push(`N${north}-E${String(east).padStart(2, "0")}`);
      }
    }
    return output;
  }

  function parseSector(code) {
    const match = /^N(\d+)-E(\d+)$/.exec(String(code || ""));
    if (!match) return null;
    const north = Number(match[1]);
    const east = Number(match[2]);
    if (north < K.VALID_GRID.northMin || north > K.VALID_GRID.northMax ||
        east < K.VALID_GRID.eastMin || east > K.VALID_GRID.eastMax) return null;
    return { north, east };
  }

  function sectorBounds(code, world = K.WORLD) {
    const parsed = parseSector(code);
    if (!parsed) return null;
    const spec = K.REFERENCE_GRID;
    const row = parsed.north - spec.startNorth;
    const col = parsed.east - spec.startEast;
    return subdividedBounds(world, spec.rows, spec.cols, row, col);
  }

  function inspectionBounds(sector, row, col) {
    const parent = sectorBounds(sector);
    if (!parent || !validIndex(row, 16) || !validIndex(col, 16)) return null;
    return subdividedBounds(parent, 16, 16, row, col);
  }

  function practicalBounds(sector, inspectionRow, inspectionCol, row, col) {
    const parent = inspectionBounds(sector, inspectionRow, inspectionCol);
    if (!parent || !validIndex(row, 8) || !validIndex(col, 8)) return null;
    return subdividedBounds(parent, 8, 8, row, col);
  }

  function subdividedBounds(parent, rows, cols, row, col) {
    const width = (parent.maxX - parent.minX) / cols;
    const height = (parent.maxY - parent.minY) / rows;
    return {
      minX: parent.minX + col * width,
      minY: parent.minY + row * height,
      maxX: parent.minX + (col + 1) * width,
      maxY: parent.minY + (row + 1) * height
    };
  }

  function inspectionCode(sector, row, col) {
    return `${sector}:r${String(row + 1).padStart(2, "0")}c${String(col + 1).padStart(2, "0")}`;
  }

  function practicalCode(sector, inspectionRow, inspectionCol, row, col) {
    return `${inspectionCode(sector, inspectionRow, inspectionCol)}:f${String(row + 1).padStart(2, "0")}c${String(col + 1).padStart(2, "0")}`;
  }

  function parseInspectionCode(code) {
    const match = /^(N\d+-E\d+):r(\d{2})c(\d{2})$/.exec(String(code || ""));
    if (!match || !parseSector(match[1])) return null;
    const row = Number(match[2]) - 1;
    const col = Number(match[3]) - 1;
    return validIndex(row, 16) && validIndex(col, 16) ? { sector: match[1], row, col } : null;
  }

  function parsePracticalCode(code) {
    const match = /^(N\d+-E\d+):r(\d{2})c(\d{2}):f(\d{2})c(\d{2})$/.exec(String(code || ""));
    if (!match || !parseSector(match[1])) return null;
    const values = match.slice(2).map((value) => Number(value) - 1);
    if (!validIndex(values[0], 16) || !validIndex(values[1], 16) ||
        !validIndex(values[2], 8) || !validIndex(values[3], 8)) return null;
    return { sector: match[1], inspectionRow: values[0], inspectionCol: values[1], row: values[2], col: values[3] };
  }

  function practicalIndex(inspectionRow, inspectionCol, row, col) {
    return ((inspectionRow * 16 + inspectionCol) * 64) + row * 8 + col;
  }

  function decodePracticalIndex(index) {
    const inspection = Math.floor(index / 64);
    const inner = index % 64;
    return {
      inspectionRow: Math.floor(inspection / 16),
      inspectionCol: inspection % 16,
      row: Math.floor(inner / 8),
      col: inner % 8
    };
  }

  function pointToSector(point) {
    const spec = K.REFERENCE_GRID;
    const cell = pointToSubcell(point, K.WORLD, spec.rows, spec.cols);
    if (!cell) return null;
    const code = `N${spec.startNorth + cell.row}-E${String(spec.startEast + cell.col).padStart(2, "0")}`;
    return parseSector(code) ? { code, row: cell.row, col: cell.col } : null;
  }

  function pointToInspection(point, sector) {
    const parent = sectorBounds(sector);
    const cell = parent ? pointToSubcell(point, parent, 16, 16) : null;
    return cell ? { sector, row: cell.row, col: cell.col, code: inspectionCode(sector, cell.row, cell.col) } : null;
  }

  function pointToPractical(point, sector, inspectionRow, inspectionCol) {
    const parent = inspectionBounds(sector, inspectionRow, inspectionCol);
    const cell = parent ? pointToSubcell(point, parent, 8, 8) : null;
    if (!cell) return null;
    return {
      sector,
      inspectionRow,
      inspectionCol,
      row: cell.row,
      col: cell.col,
      index: practicalIndex(inspectionRow, inspectionCol, cell.row, cell.col),
      code: practicalCode(sector, inspectionRow, inspectionCol, cell.row, cell.col)
    };
  }

  function pointToSubcell(point, bounds, rows, cols) {
    if (!contains(bounds, point)) return null;
    const x = Math.min(cols - 1, Math.floor(((point[0] - bounds.minX) / (bounds.maxX - bounds.minX)) * cols));
    const y = Math.min(rows - 1, Math.floor(((point[1] - bounds.minY) / (bounds.maxY - bounds.minY)) * rows));
    return { row: y, col: x };
  }

  function contains(bounds, point) {
    return point[0] >= bounds.minX && point[0] <= bounds.maxX &&
      point[1] >= bounds.minY && point[1] <= bounds.maxY;
  }

  function intersects(a, b) {
    return a.minX <= b.maxX && a.maxX >= b.minX && a.minY <= b.maxY && a.maxY >= b.minY;
  }

  function validIndex(value, size) {
    return Number.isInteger(value) && value >= 0 && value < size;
  }

  CFM.grid = {
    sectorCodes: Object.freeze(sectorCodes()),
    parseSector,
    sectorBounds,
    inspectionBounds,
    practicalBounds,
    inspectionCode,
    practicalCode,
    parseInspectionCode,
    parsePracticalCode,
    practicalIndex,
    decodePracticalIndex,
    pointToSector,
    pointToInspection,
    pointToPractical,
    contains,
    intersects
  };
})(window);
