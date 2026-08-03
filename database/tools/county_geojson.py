#!/usr/bin/env python3
"""Validate GeoJSON geometry contracts used by authoritative ArcGIS harvests."""

from __future__ import annotations

import math
from typing import Any

ARCGIS_GEOJSON_TYPES = {
    "esriGeometryPolygon": ("Polygon", "MultiPolygon"),
    "esriGeometryPolyline": ("LineString", "MultiLineString"),
}


def expected_geojson_types(arcgis_type: str) -> tuple[str, ...]:
    try:
        return ARCGIS_GEOJSON_TYPES[arcgis_type]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported ArcGIS geometry contract: {arcgis_type!r}.") from exc


def point(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) < 2:
        raise RuntimeError(f"{label} is not a coordinate pair.")
    x, y = value[0], value[1]
    if isinstance(x, bool) or isinstance(y, bool):
        raise RuntimeError(f"{label} contains a nonnumeric coordinate.")
    try:
        x_value = float(x)
        y_value = float(y)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} contains a nonnumeric coordinate.") from exc
    if not math.isfinite(x_value) or not math.isfinite(y_value):
        raise RuntimeError(f"{label} contains a nonfinite coordinate.")
    return x_value, y_value


def validate_path(path: Any, label: str, minimum: int) -> None:
    if not isinstance(path, list) or len(path) < minimum:
        raise RuntimeError(f"{label} must contain at least {minimum} coordinate pairs.")
    for index, value in enumerate(path, start=1):
        point(value, f"{label} point {index}")


def validate_ring(ring: Any, label: str) -> None:
    validate_path(ring, label, 4)
    first = point(ring[0], f"{label} first point")
    last = point(ring[-1], f"{label} last point")
    if first != last:
        raise RuntimeError(f"{label} is not closed.")


def validate_polygon(polygon: Any, label: str) -> None:
    if not isinstance(polygon, list) or not polygon:
        raise RuntimeError(f"{label} contains no rings.")
    for index, ring in enumerate(polygon, start=1):
        validate_ring(ring, f"{label} ring {index}")


def validate_geometry(geometry: Any, arcgis_type: str, feature_label: str = "feature") -> str:
    if not isinstance(geometry, dict):
        raise RuntimeError(f"GeoJSON {feature_label} geometry is missing or invalid.")
    geometry_type = geometry.get("type")
    allowed = expected_geojson_types(arcgis_type)
    if geometry_type not in allowed:
        expected = " or ".join(allowed)
        raise RuntimeError(
            f"GeoJSON {feature_label} geometry is {geometry_type!r}; expected {expected}."
        )
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        validate_path(coordinates, f"GeoJSON {feature_label} LineString", 2)
    elif geometry_type == "MultiLineString":
        if not isinstance(coordinates, list) or not coordinates:
            raise RuntimeError(f"GeoJSON {feature_label} MultiLineString contains no paths.")
        for index, path in enumerate(coordinates, start=1):
            validate_path(path, f"GeoJSON {feature_label} path {index}", 2)
    elif geometry_type == "Polygon":
        validate_polygon(coordinates, f"GeoJSON {feature_label} Polygon")
    else:
        if not isinstance(coordinates, list) or not coordinates:
            raise RuntimeError(f"GeoJSON {feature_label} MultiPolygon contains no polygons.")
        for index, polygon in enumerate(coordinates, start=1):
            validate_polygon(polygon, f"GeoJSON {feature_label} polygon {index}")
    return str(geometry_type)
