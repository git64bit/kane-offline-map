#!/usr/bin/env python3
"""Pure-Python Polygon and MultiPolygon decoding and rectangle intersection."""

from __future__ import annotations

import struct

class WkbReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def take(self, length: int) -> bytes:
        end = self.offset + length
        if end > len(self.data):
            raise RuntimeError("Building geometry WKB is truncated.")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def uint32(self, endian: str) -> int:
        return struct.unpack(endian + "I", self.take(4))[0]

    def point(self, endian: str) -> tuple[float, float]:
        return struct.unpack(endian + "dd", self.take(16))


def read_polygon(reader: WkbReader, nested: bool = False) -> list[list[tuple[float, float]]]:
    order = reader.take(1)[0]
    if order not in (0, 1):
        raise RuntimeError("Building geometry WKB has an invalid byte order.")
    endian = "<" if order == 1 else ">"
    geometry_type = reader.uint32(endian)
    if geometry_type != 3:
        label = "nested " if nested else ""
        raise RuntimeError(f"Building geometry WKB {label}type is not Polygon.")
    rings: list[list[tuple[float, float]]] = []
    for _ in range(reader.uint32(endian)):
        rings.append([reader.point(endian) for _ in range(reader.uint32(endian))])
    return rings


def decode_geometry(blob: bytes) -> list[list[list[tuple[float, float]]]]:
    if len(blob) < 45 or blob[:2] != b"GP":
        raise RuntimeError("Building geometry has an invalid GeoPackage header.")
    flags = blob[3]
    envelope_code = (flags >> 1) & 0b111
    envelope_lengths = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope_code not in envelope_lengths:
        raise RuntimeError("Building geometry has an unsupported GeoPackage envelope.")
    header_length = 8 + envelope_lengths[envelope_code]
    reader = WkbReader(blob[header_length:])
    order = reader.take(1)[0]
    if order not in (0, 1):
        raise RuntimeError("Building geometry WKB has an invalid byte order.")
    endian = "<" if order == 1 else ">"
    geometry_type = reader.uint32(endian)
    if geometry_type == 3:
        reader.offset = 0
        polygons = [read_polygon(reader)]
    elif geometry_type == 6:
        polygons = [read_polygon(reader, nested=True) for _ in range(reader.uint32(endian))]
    else:
        raise RuntimeError("Building geometry WKB is not Polygon or MultiPolygon.")
    if reader.offset != len(reader.data):
        raise RuntimeError("Building geometry WKB has trailing bytes.")
    return polygons


def point_on_segment(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    px, py = point
    ax, ay = a
    bx, by = b
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > 1e-12:
        return False
    return min(ax, bx) - 1e-12 <= px <= max(ax, bx) + 1e-12 and min(ay, by) - 1e-12 <= py <= max(ay, by) + 1e-12


def point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    inside = False
    for index in range(len(ring) - 1):
        a, b = ring[index], ring[index + 1]
        if point_on_segment(point, a, b):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            x_cross = (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]
            if point[0] < x_cross:
                inside = not inside
    return inside


def point_in_polygon(point: tuple[float, float], polygon: list[list[tuple[float, float]]]) -> bool:
    if not polygon or not point_in_ring(point, polygon[0]):
        return False
    return not any(point_in_ring(point, hole) for hole in polygon[1:])


def orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]
) -> bool:
    o1, o2, o3, o4 = orientation(a, b, c), orientation(a, b, d), orientation(c, d, a), orientation(c, d, b)
    if ((o1 > 0 and o2 < 0) or (o1 < 0 and o2 > 0)) and ((o3 > 0 and o4 < 0) or (o3 < 0 and o4 > 0)):
        return True
    return (
        (abs(o1) <= 1e-12 and point_on_segment(c, a, b))
        or (abs(o2) <= 1e-12 and point_on_segment(d, a, b))
        or (abs(o3) <= 1e-12 and point_on_segment(a, c, d))
        or (abs(o4) <= 1e-12 and point_on_segment(b, c, d))
    )


def polygon_intersects_rect(
    polygon: list[list[tuple[float, float]]], rect: tuple[float, float, float, float]
) -> bool:
    min_x, min_y, max_x, max_y = rect
    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    for ring in polygon:
        if any(min_x <= x <= max_x and min_y <= y <= max_y for x, y in ring):
            return True
        for index in range(len(ring) - 1):
            if any(segments_intersect(ring[index], ring[index + 1], start, end) for start, end in edges):
                return True
    return any(point_in_polygon(corner, polygon) for corner in corners)


def geometry_intersects_rect(
    polygons: list[list[list[tuple[float, float]]]], rect: tuple[float, float, float, float]
) -> bool:
    return any(polygon_intersects_rect(polygon, rect) for polygon in polygons)
