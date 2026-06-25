from __future__ import annotations

from scripts.combine_species_and_higher_taxa import (
    add_lookup_type,
    sort_lookup_rows,
    union_headers,
)


def test_union_headers_places_lookup_type_first_and_preserves_order() -> None:
    assert union_headers(["ScientificName", "TaxonId"], ["scientific_name", "TaxonId"]) == [
        "lookup_type",
        "ScientificName",
        "TaxonId",
        "scientific_name",
    ]


def test_add_lookup_type_marks_rows() -> None:
    assert add_lookup_type([{"ScientificName": "Urtica"}], "higher_taxon") == [
        {"ScientificName": "Urtica", "lookup_type": "higher_taxon"}
    ]


def test_add_lookup_type_sets_species_rank() -> None:
    assert add_lookup_type([{"ScientificName": "Urtica dioica", "rank": "species"}], "species") == [
        {
            "ScientificName": "Urtica dioica",
            "rank": "species",
            "lookup_type": "species",
            "taxon_rank": "species",
            "taxon_rank_source": "inaturalist",
        }
    ]


def test_sort_lookup_rows_puts_higher_taxa_before_species() -> None:
    rows = sort_lookup_rows(
        [
            {"lookup_type": "species", "ScientificName": "Urtica dioica"},
            {"lookup_type": "higher_taxon", "ScientificName": "Plantae"},
            {"lookup_type": "higher_taxon", "ScientificName": "Urtica"},
        ]
    )

    assert [row["ScientificName"] for row in rows] == ["Plantae", "Urtica", "Urtica dioica"]
