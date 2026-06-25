#!/usr/bin/env python3
"""Prune an MBTiles raster basemap to tiles intersecting a KML polygon."""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

Point = tuple[float, float]
Tile = tuple[int, int, int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a smaller MBTiles file by keeping tiles near a KML polygon."
    )
    parser.add_argument("--mbtiles", required=True, type=Path, help="Input MBTiles file")
    parser.add_argument("--polygon", required=True, type=Path, help="Input KML polygon")
    parser.add_argument("--output", required=True, type=Path, help="Output MBTiles file")
    parser.add_argument(
        "--buffer-tiles",
        type=int,
        default=1,
        help="Number of neighboring tile cells to keep around the polygon at each zoom",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists",
    )
    return parser.parse_args()


def read_kml_polygon(path: Path) -> list[Point]:
    root = ET.parse(path).getroot()
    coordinates = None
    for element in root.iter():
        if element.tag.endswith("coordinates") and element.text:
            coordinates = element.text
            break
    if not coordinates:
        raise ValueError(f"No KML coordinates found in {path}")

    polygon: list[Point] = []
    for chunk in coordinates.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        polygon.append((float(parts[0]), float(parts[1])))

    if len(polygon) < 4:
        raise ValueError(f"Expected a polygon ring in {path}, found {len(polygon)} points")
    if polygon[0] != polygon[-1]:
        polygon.append(polygon[0])
    return polygon


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    x, y = point
    inside = False
    previous = len(polygon) - 1
    for current, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[previous]
        crosses = (yi > y) != (yj > y)
        if crosses:
            x_at_y = (xj - xi) * (y - yi) / ((yj - yi) or 1e-30) + xi
            if x < x_at_y:
                inside = not inside
        previous = current
    return inside


def orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(a: Point, b: Point, c: Point) -> bool:
    return (
        min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])
        and abs(orientation(a, b, c)) < 1e-12
    )


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1 = orientation(a, b, c)
    o2 = orientation(a, b, d)
    o3 = orientation(c, d, a)
    o4 = orientation(c, d, b)

    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return (
        on_segment(a, b, c)
        or on_segment(a, b, d)
        or on_segment(c, d, a)
        or on_segment(c, d, b)
    )


def tile_bounds(zoom: int, column: int, tms_row: int) -> tuple[float, float, float, float]:
    xyz_row = (1 << zoom) - 1 - tms_row
    scale = 1 << zoom
    west = column / scale * 360.0 - 180.0
    east = (column + 1) / scale * 360.0 - 180.0

    def row_to_lat(row: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / scale))))

    north = row_to_lat(xyz_row)
    south = row_to_lat(xyz_row + 1)
    return west, south, east, north


def tile_intersects_polygon(bounds: tuple[float, float, float, float], polygon: list[Point]) -> bool:
    west, south, east, north = bounds
    corners = [(west, south), (west, north), (east, north), (east, south)]

    if any(point_in_polygon(corner, polygon) for corner in corners):
        return True
    if any(west <= lon <= east and south <= lat <= north for lon, lat in polygon):
        return True

    box_edges = list(zip(corners, corners[1:] + corners[:1]))
    polygon_edges = list(zip(polygon, polygon[1:]))
    return any(
        segments_intersect(box_start, box_end, poly_start, poly_end)
        for box_start, box_end in box_edges
        for poly_start, poly_end in polygon_edges
    )


def buffered_tiles(intersecting: set[Tile], existing: set[Tile], buffer_tiles: int) -> set[Tile]:
    if buffer_tiles <= 0:
        return intersecting

    kept: set[Tile] = set()
    for zoom, column, row in intersecting:
        max_index = (1 << zoom) - 1
        for dx in range(-buffer_tiles, buffer_tiles + 1):
            for dy in range(-buffer_tiles, buffer_tiles + 1):
                buffered = (zoom, column + dx, row + dy)
                if 0 <= buffered[1] <= max_index and 0 <= buffered[2] <= max_index:
                    if buffered in existing:
                        kept.add(buffered)
    return kept


def metadata_bounds(tiles: set[Tile]) -> str:
    bounds = [tile_bounds(*tile) for tile in tiles]
    west = min(bound[0] for bound in bounds)
    south = min(bound[1] for bound in bounds)
    east = max(bound[2] for bound in bounds)
    north = max(bound[3] for bound in bounds)
    return f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}"


def create_pruned_mbtiles(input_path: Path, output_path: Path, polygon: list[Point], buffer_tiles: int) -> None:
    source = sqlite3.connect(f"file:{input_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    existing: set[Tile] = {
        (row["zoom_level"], row["tile_column"], row["tile_row"])
        for row in source.execute("select zoom_level, tile_column, tile_row from tiles")
    }

    intersecting = {
        tile
        for tile in existing
        if tile_intersects_polygon(tile_bounds(*tile), polygon)
    }
    kept = buffered_tiles(intersecting, existing, buffer_tiles)
    if not kept:
        raise ValueError("No tiles intersect the polygon")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp", delete=False
    ) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        destination = sqlite3.connect(temp_path)
        destination.execute("pragma synchronous = off")
        destination.execute("pragma journal_mode = off")
        destination.execute("create table metadata (name text, value text)")
        destination.execute(
            "create table tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)"
        )
        destination.execute("create unique index tile_index on tiles (zoom_level, tile_column, tile_row)")
        destination.execute(
            "create temporary table kept_tiles ("
            "zoom_level integer, tile_column integer, tile_row integer, "
            "primary key (zoom_level, tile_column, tile_row)"
            ")"
        )

        metadata = {
            row["name"]: row["value"]
            for row in source.execute("select name, value from metadata")
        }
        zooms = sorted({tile[0] for tile in kept})
        metadata["bounds"] = metadata_bounds(kept)
        metadata["minzoom"] = str(min(zooms))
        metadata["maxzoom"] = str(max(zooms))
        destination.executemany(
            "insert into metadata (name, value) values (?, ?)",
            sorted(metadata.items()),
        )

        destination.executemany(
            "insert into kept_tiles (zoom_level, tile_column, tile_row) values (?, ?, ?)",
            sorted(kept),
        )
        source.close()
        destination.execute("attach database ? as source", (str(input_path),))
        destination.execute(
            "insert into tiles (zoom_level, tile_column, tile_row, tile_data) "
            "select source.tiles.zoom_level, source.tiles.tile_column, "
            "source.tiles.tile_row, source.tiles.tile_data "
            "from source.tiles "
            "join kept_tiles using (zoom_level, tile_column, tile_row)"
        )

        destination.commit()
        destination.close()
        os.replace(temp_path, output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    print(f"Input tiles: {len(existing)}")
    print(f"Intersecting tiles: {len(intersecting)}")
    print(f"Output tiles with buffer {buffer_tiles}: {len(kept)}")
    print(f"Output: {output_path}")


def main() -> int:
    args = parse_args()
    if args.buffer_tiles < 0:
        print("--buffer-tiles must be zero or greater", file=sys.stderr)
        return 2
    if args.output.exists() and not args.force:
        print(f"Output already exists: {args.output}. Use --force to replace it.", file=sys.stderr)
        return 2

    polygon = read_kml_polygon(args.polygon)
    create_pruned_mbtiles(args.mbtiles, args.output, polygon, args.buffer_tiles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
