#!/usr/bin/env python3
"""Fetch species observed in the Manaslu field region from iNaturalist."""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pycountry
from pyinaturalist import get_observation_species_counts
from pyinaturalist import get_places_autocomplete


DEFAULT_OUTPUT = Path("data/inaturalist/manaslu_species_observations.csv")

# Bounds of qgis/manaslu/optimized_maps/Manaslu-EMI.gpkg in EPSG:4326.
DEFAULT_SWLAT = 28.56279819824349
DEFAULT_SWLNG = 84.61560318948491
DEFAULT_NELAT = 28.61564911652461
DEFAULT_NELNG = 84.70745261429477

CSV_FIELDS = [
    "taxon_id",
    "scientific_name",
    "rank",
    "common_name",
    "iconic_taxon_name",
    "observations_in_region",
    "inat_observations_global",
    "wikipedia_url",
    "photo_url",
    "photo_license_code",
    "photo_attribution",
]


@dataclass(frozen=True)
class BBox:
    swlat: float
    swlng: float
    nelat: float
    nelng: float

    @classmethod
    def parse(cls, value: str) -> BBox:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 4:
            raise argparse.ArgumentTypeError(
                "--bbox must use 'swlat,swlng,nelat,nelng' order"
            )
        try:
            swlat, swlng, nelat, nelng = (float(part) for part in parts)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("--bbox values must be numbers") from exc
        bbox = cls(swlat=swlat, swlng=swlng, nelat=nelat, nelng=nelng)
        bbox.validate()
        return bbox

    def validate(self) -> None:
        if not -90 <= self.swlat <= 90 or not -90 <= self.nelat <= 90:
            raise argparse.ArgumentTypeError("bbox latitudes must be between -90 and 90")
        if not -180 <= self.swlng <= 180 or not -180 <= self.nelng <= 180:
            raise argparse.ArgumentTypeError("bbox longitudes must be between -180 and 180")
        if self.swlat >= self.nelat:
            raise argparse.ArgumentTypeError("bbox swlat must be south of nelat")
        if self.swlng >= self.nelng:
            raise argparse.ArgumentTypeError("bbox swlng must be west of nelng")


DEFAULT_BBOX = BBox(DEFAULT_SWLAT, DEFAULT_SWLNG, DEFAULT_NELAT, DEFAULT_NELNG)


def resolve_bbox(args: argparse.Namespace) -> BBox:
    edge_values = {
        "south": args.south,
        "west": args.west,
        "north": args.north,
        "east": args.east,
    }
    provided_edges = {name: value for name, value in edge_values.items() if value is not None}
    if args.bbox is not None and provided_edges:
        raise argparse.ArgumentTypeError("Use either --bbox or --south/--west/--north/--east")
    if args.bbox is not None:
        return args.bbox
    if provided_edges:
        missing = [name for name, value in edge_values.items() if value is None]
        if missing:
            names = ", ".join(f"--{name}" for name in missing)
            raise argparse.ArgumentTypeError(f"Missing coordinate argument(s): {names}")
        bbox = BBox(
            swlat=args.south,
            swlng=args.west,
            nelat=args.north,
            nelng=args.east,
        )
        bbox.validate()
        return bbox
    return DEFAULT_BBOX


def uses_bbox_args(args: argparse.Namespace) -> bool:
    return (
        args.bbox is not None
        or args.south is not None
        or args.west is not None
        or args.north is not None
        or args.east is not None
    )


def country_name_from_code(country_code: str) -> str:
    normalized_code = country_code.strip().upper()
    country = pycountry.countries.get(alpha_2=normalized_code)
    if country is None:
        country = pycountry.countries.get(alpha_3=normalized_code)
    if country is None:
        raise argparse.ArgumentTypeError(f"Unknown ISO country code: {country_code}")
    return country.name


def resolve_country_place_id(
    country_code: str,
    *,
    lookup_places: Callable[..., dict[str, Any]] = get_places_autocomplete,
) -> tuple[int, str]:
    country_name = country_name_from_code(country_code)
    response = lookup_places(q=country_name, per_page=20)
    results = response.get("results", [])
    normalized_name = country_name.casefold()
    country_places = [place for place in results if place.get("admin_level") == 0]
    exact_matches = [
        place
        for place in country_places
        if str(place.get("name", "")).casefold() == normalized_name
        or str(place.get("display_name", "")).casefold() == normalized_name
    ]
    candidates = exact_matches or country_places
    if not candidates:
        raise argparse.ArgumentTypeError(
            f"Could not resolve country code {country_code!r} to an iNaturalist place"
        )
    return int(candidates[0]["id"]), country_name


def resolve_search_area(args: argparse.Namespace) -> None:
    place_args = [value is not None for value in [args.place_id, args.country_code]]
    if sum(place_args) > 1:
        raise argparse.ArgumentTypeError("Use only one of --place-id or --country-code")
    if any(place_args) and uses_bbox_args(args):
        raise argparse.ArgumentTypeError(
            "Use either a place/country search or a bounding-box search, not both"
        )
    if args.place_id is not None:
        args.resolved_bbox = None
        args.resolved_place_id = args.place_id
        args.resolved_country_code = None
        args.resolved_country_name = None
        return
    if args.country_code is not None:
        place_id, country_name = resolve_country_place_id(args.country_code)
        args.resolved_bbox = None
        args.resolved_place_id = place_id
        args.resolved_country_code = args.country_code.upper()
        args.resolved_country_name = country_name
        return
    args.resolved_bbox = resolve_bbox(args)
    args.resolved_place_id = None
    args.resolved_country_code = None
    args.resolved_country_name = None


def normalize_text(value: Any) -> str:
    return "" if value is None else str(value)


def taxon_photo(taxon: dict[str, Any]) -> dict[str, Any]:
    photo = taxon.get("default_photo")
    return photo if isinstance(photo, dict) else {}


def taxon_count_to_row(item: dict[str, Any]) -> dict[str, str]:
    taxon = item.get("taxon")
    if not isinstance(taxon, dict):
        taxon = {}
    photo = taxon_photo(taxon)
    return {
        "taxon_id": normalize_text(taxon.get("id")),
        "scientific_name": normalize_text(taxon.get("name")),
        "rank": normalize_text(taxon.get("rank")),
        "common_name": normalize_text(taxon.get("preferred_common_name")),
        "iconic_taxon_name": normalize_text(taxon.get("iconic_taxon_name")),
        "observations_in_region": normalize_text(item.get("count")),
        "inat_observations_global": normalize_text(taxon.get("observations_count")),
        "wikipedia_url": normalize_text(taxon.get("wikipedia_url")),
        "photo_url": normalize_text(photo.get("medium_url") or photo.get("url")),
        "photo_license_code": normalize_text(photo.get("license_code")),
        "photo_attribution": normalize_text(photo.get("attribution")),
    }


def sorted_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        rows,
        key=lambda row: (
            -int(row["observations_in_region"] or 0),
            row["scientific_name"].lower(),
        ),
    )


def fetch_species_counts(
    *,
    bbox: BBox | None,
    place_id: int | None,
    iconic_taxa: list[str] | None,
    quality_grade: str | None,
    per_page: int,
    max_pages: int | None,
    fetch_page: Callable[..., dict[str, Any]] = get_observation_species_counts,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    page = 1
    while True:
        location_params: dict[str, float | int] = {}
        if bbox is not None:
            location_params.update(
                swlat=bbox.swlat,
                swlng=bbox.swlng,
                nelat=bbox.nelat,
                nelng=bbox.nelng,
            )
        if place_id is not None:
            location_params["place_id"] = place_id
        response = fetch_page(
            **location_params,
            iconic_taxa=iconic_taxa,
            quality_grade=quality_grade,
            rank="species",
            per_page=per_page,
            page=page,
            order="desc",
            order_by="observations_count",
        )
        results = response.get("results", [])
        rows.extend(taxon_count_to_row(item) for item in results)

        total_results = int(response.get("total_results") or len(rows))
        if len(rows) >= total_results:
            break
        if not results:
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1
    return sorted_rows(rows)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_metadata(path: Path, args: argparse.Namespace, row_count: int) -> None:
    metadata_path = path.with_suffix(".metadata.txt")
    bbox = args.resolved_bbox
    lines = [
        "iNaturalist species counts for the Manaslu field region",
        f"created_at_utc={datetime.now(timezone.utc).isoformat()}",
        "source=pyinaturalist.get_observation_species_counts",
        f"place_id={args.resolved_place_id or ''}",
        f"country_code={args.resolved_country_code or ''}",
        f"country_name={args.resolved_country_name or ''}",
        f"bbox_swlat={bbox.swlat if bbox else ''}",
        f"bbox_swlng={bbox.swlng if bbox else ''}",
        f"bbox_nelat={bbox.nelat if bbox else ''}",
        f"bbox_nelng={bbox.nelng if bbox else ''}",
        f"quality_grade={args.quality_grade or ''}",
        f"iconic_taxa={','.join(args.iconic_taxa or [])}",
        f"per_page={args.per_page}",
        f"max_pages={args.max_pages or ''}",
        f"row_count={row_count}",
        "note=The default query uses a bounding box around the Manaslu polygon. "
        "Country queries use iNaturalist place IDs.",
    ]
    metadata_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch species-level iNaturalist observation counts for the Manaslu "
            "region and write a CSV collection-list candidate file."
        )
    )
    parser.add_argument(
        "--bbox",
        type=BBox.parse,
        default=None,
        help=(
            "Bounding box as swlat,swlng,nelat,nelng. Defaults to the "
            "Manaslu-EMI polygon extent."
        ),
    )
    parser.add_argument(
        "--south",
        type=float,
        default=None,
        help="Southern latitude of the search box.",
    )
    parser.add_argument(
        "--west",
        type=float,
        default=None,
        help="Western longitude of the search box.",
    )
    parser.add_argument(
        "--north",
        type=float,
        default=None,
        help="Northern latitude of the search box.",
    )
    parser.add_argument(
        "--east",
        type=float,
        default=None,
        help="Eastern longitude of the search box.",
    )
    parser.add_argument(
        "--place-id",
        type=int,
        default=None,
        help="iNaturalist place ID to search instead of a bounding box.",
    )
    parser.add_argument(
        "--country-code",
        default=None,
        help="ISO 3166-1 alpha-2 or alpha-3 country code, e.g. NP or NPL for Nepal.",
    )
    parser.add_argument(
        "--iconic-taxa",
        nargs="+",
        default=None,
        help="Optional iNaturalist iconic taxa filter, e.g. Plantae Fungi.",
    )
    parser.add_argument(
        "--quality-grade",
        default="any",
        choices=["research", "needs_id", "casual", "any"],
        help="Observation quality grade filter. Use 'any' to omit this filter.",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=200,
        help="Results per API page. pyinaturalist/iNaturalist generally allow up to 200.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional page limit for quick test runs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output CSV path. Default: {DEFAULT_OUTPUT}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        resolve_search_area(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    quality_grade = None if args.quality_grade == "any" else args.quality_grade
    rows = fetch_species_counts(
        bbox=args.resolved_bbox,
        place_id=args.resolved_place_id,
        iconic_taxa=args.iconic_taxa,
        quality_grade=quality_grade,
        per_page=args.per_page,
        max_pages=args.max_pages,
    )
    write_csv(args.output, rows)
    write_metadata(args.output, args, len(rows))
    print(f"Wrote {len(rows)} species rows to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
