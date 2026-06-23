from __future__ import annotations

import argparse
import csv

import pytest

from scripts.fetch_inaturalist_species import (
    BBox,
    DEFAULT_BBOX,
    country_name_from_code,
    fetch_species_counts,
    resolve_country_place_id,
    resolve_bbox,
    resolve_search_area,
    taxon_count_to_row,
    write_csv,
)


def test_bbox_parse_validates_order() -> None:
    bbox = BBox.parse("28.5,84.6,28.7,84.8")

    assert bbox.swlat == 28.5
    assert bbox.swlng == 84.6
    assert bbox.nelat == 28.7
    assert bbox.nelng == 84.8


@pytest.mark.parametrize(
    "value",
    [
        "28.5,84.6,28.4,84.8",
        "28.5,84.9,28.7,84.8",
        "28.5,84.6,28.7",
        "north,84.6,28.7,84.8",
    ],
)
def test_bbox_parse_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        BBox.parse(value)


def test_resolve_bbox_defaults_to_manaslu_extent() -> None:
    args = argparse.Namespace(
        bbox=None,
        south=None,
        west=None,
        north=None,
        east=None,
    )

    assert resolve_bbox(args) == DEFAULT_BBOX


def test_resolve_bbox_accepts_named_edges() -> None:
    args = argparse.Namespace(
        bbox=None,
        south=28.5,
        west=84.6,
        north=28.7,
        east=84.8,
    )

    assert resolve_bbox(args) == BBox(28.5, 84.6, 28.7, 84.8)


def test_resolve_bbox_rejects_mixed_bbox_styles() -> None:
    args = argparse.Namespace(
        bbox=BBox(28.5, 84.6, 28.7, 84.8),
        south=28.5,
        west=None,
        north=None,
        east=None,
    )

    with pytest.raises(argparse.ArgumentTypeError, match="Use either"):
        resolve_bbox(args)


def test_resolve_bbox_requires_all_named_edges() -> None:
    args = argparse.Namespace(
        bbox=None,
        south=28.5,
        west=84.6,
        north=None,
        east=84.8,
    )

    with pytest.raises(argparse.ArgumentTypeError, match="--north"):
        resolve_bbox(args)


def test_country_name_from_code_accepts_alpha2_and_alpha3() -> None:
    assert country_name_from_code("NP") == "Nepal"
    assert country_name_from_code("npl") == "Nepal"


def test_resolve_country_place_id_uses_inaturalist_country_place() -> None:
    def fake_lookup_places(**kwargs: object) -> dict[str, object]:
        assert kwargs["q"] == "Nepal"
        return {
            "results": [
                {"id": 123, "name": "Some Nepal Place", "admin_level": None},
                {"id": 7335, "name": "Nepal", "display_name": "Nepal", "admin_level": 0},
            ]
        }

    assert resolve_country_place_id("NP", lookup_places=fake_lookup_places) == (7335, "Nepal")


def test_resolve_search_area_rejects_country_and_bbox() -> None:
    args = argparse.Namespace(
        bbox=BBox(28.5, 84.6, 28.7, 84.8),
        south=None,
        west=None,
        north=None,
        east=None,
        place_id=None,
        country_code="NP",
    )

    with pytest.raises(argparse.ArgumentTypeError, match="not both"):
        resolve_search_area(args)


def test_taxon_count_to_row_extracts_expected_fields() -> None:
    row = taxon_count_to_row(
        {
            "count": 12,
            "taxon": {
                "id": 47126,
                "name": "Rhododendron arboreum",
                "rank": "species",
                "preferred_common_name": "tree rhododendron",
                "iconic_taxon_name": "Plantae",
                "observations_count": 1234,
                "wikipedia_url": "https://example.test/rhododendron",
                "default_photo": {
                    "medium_url": "https://example.test/photo.jpg",
                    "license_code": "cc-by-nc",
                    "attribution": "(c) observer",
                },
            },
        }
    )

    assert row == {
        "taxon_id": "47126",
        "scientific_name": "Rhododendron arboreum",
        "rank": "species",
        "common_name": "tree rhododendron",
        "iconic_taxon_name": "Plantae",
        "observations_in_region": "12",
        "inat_observations_global": "1234",
        "wikipedia_url": "https://example.test/rhododendron",
        "photo_url": "https://example.test/photo.jpg",
        "photo_license_code": "cc-by-nc",
        "photo_attribution": "(c) observer",
    }


def test_fetch_species_counts_paginates_and_sorts() -> None:
    calls: list[dict[str, object]] = []

    def fake_fetch_page(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        page = kwargs["page"]
        if page == 1:
            return {
                "total_results": 3,
                "results": [
                    {"count": 1, "taxon": {"id": 2, "name": "Beta", "rank": "species"}},
                    {"count": 5, "taxon": {"id": 1, "name": "Alpha", "rank": "species"}},
                ],
            }
        return {
            "total_results": 3,
            "results": [
                {"count": 5, "taxon": {"id": 3, "name": "Aardvark", "rank": "species"}},
            ],
        }

    rows = fetch_species_counts(
        bbox=BBox(28.5, 84.6, 28.7, 84.8),
        place_id=None,
        iconic_taxa=["Plantae"],
        quality_grade="research",
        per_page=2,
        max_pages=None,
        fetch_page=fake_fetch_page,
    )

    assert [call["page"] for call in calls] == [1, 2]
    assert calls[0]["iconic_taxa"] == ["Plantae"]
    assert calls[0]["quality_grade"] == "research"
    assert calls[0]["order"] == "desc"
    assert calls[0]["swlat"] == 28.5
    assert [row["scientific_name"] for row in rows] == ["Aardvark", "Alpha", "Beta"]


def test_fetch_species_counts_can_use_place_id() -> None:
    calls: list[dict[str, object]] = []

    def fake_fetch_page(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "total_results": 1,
            "results": [
                {"count": 7, "taxon": {"id": 1, "name": "Primula denticulata"}},
            ],
        }

    rows = fetch_species_counts(
        bbox=None,
        place_id=7335,
        iconic_taxa=None,
        quality_grade=None,
        per_page=200,
        max_pages=None,
        fetch_page=fake_fetch_page,
    )

    assert calls[0]["place_id"] == 7335
    assert "swlat" not in calls[0]
    assert rows[0]["scientific_name"] == "Primula denticulata"


def test_write_csv_creates_parent_and_header(tmp_path) -> None:
    output = tmp_path / "nested" / "species.csv"

    write_csv(
        output,
        [
            taxon_count_to_row(
                {"count": 1, "taxon": {"id": 42, "name": "Primula denticulata"}}
            )
        ],
    )

    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["taxon_id"] == "42"
    assert rows[0]["scientific_name"] == "Primula denticulata"
