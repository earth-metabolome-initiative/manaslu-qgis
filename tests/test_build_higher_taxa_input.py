from __future__ import annotations

from scripts.build_higher_taxa_input import (
    infer_taxon_rank,
    iter_higher_taxa,
    sorted_summary_rows,
    split_classification_path,
)


def test_split_classification_path_ignores_empty_parts() -> None:
    assert split_classification_path("Life| Plantae || Urtica ") == [
        "Life",
        "Plantae",
        "Urtica",
    ]


def test_iter_higher_taxa_removes_terminal_species_and_adds_life() -> None:
    summaries = iter_higher_taxa(
        [
            {
                "ScientificName": "Urtica dioica",
                "ClassificationPath": "Eukaryota|Plantae|Urticaceae|Urtica|Urtica dioica",
            }
        ],
        classification_header="ClassificationPath",
        name_headers=["ScientificName"],
        include_life=True,
    )

    assert set(summaries) == {"Life", "Eukaryota", "Plantae", "Urticaceae", "Urtica"}
    assert "Urtica dioica" not in summaries
    assert summaries["Urtica"].source_species == {"Urtica dioica"}
    assert summaries["Life"].path_depths == {1}


def test_iter_higher_taxa_counts_unique_source_species_once_per_taxon() -> None:
    summaries = iter_higher_taxa(
        [
            {
                "ScientificName": "Urtica dioica",
                "ClassificationPath": "Eukaryota|Plantae|Urticaceae|Urtica|Urtica dioica",
            },
            {
                "ScientificName": "Urtica dioica",
                "ClassificationPath": "Eukaryota|Plantae|Urticaceae|Urtica|Urtica dioica",
            },
            {
                "ScientificName": "Urtica ardens",
                "ClassificationPath": "Eukaryota|Plantae|Urticaceae|Urtica|Urtica ardens",
            },
        ],
        classification_header="ClassificationPath",
        name_headers=["ScientificName"],
        include_life=False,
    )

    rows = {row["scientific_name"]: row for row in sorted_summary_rows(summaries)}
    assert rows["Urtica"]["source_species_count"] == "2"
    assert rows["Urtica"]["taxon_rank"] == "genus"
    assert rows["Urticaceae"]["source_species_count"] == "2"
    assert rows["Urticaceae"]["taxon_rank"] == "family"
    assert rows["Eukaryota"]["path_depth_min"] == "1"
    assert rows["Eukaryota"]["taxon_rank"] == "domain"


def test_iter_higher_taxa_excludes_rank_marker_artifacts() -> None:
    summaries = iter_higher_taxa(
        [
            {
                "ScientificName": "Senegalia catechu",
                "ClassificationPath": "Eukaryota|Plantae|Fabaceae|Senegalia|sect.|Senegalia catechu",
            }
        ],
        classification_header="ClassificationPath",
        name_headers=["ScientificName"],
        include_life=False,
    )

    assert "sect." not in summaries
    assert "Senegalia" in summaries


def test_iter_higher_taxa_excludes_source_species_names_from_ancestors() -> None:
    summaries = iter_higher_taxa(
        [
            {
                "ScientificName": "Achelura bifasciata",
                "ClassificationPath": "Animalia|Arthropoda|Achelura|Achelura bifasciata|Achelura bifasciata",
            }
        ],
        classification_header="ClassificationPath",
        name_headers=["ScientificName"],
        include_life=False,
    )

    assert "Achelura" in summaries
    assert "Achelura bifasciata" not in summaries


def test_infer_taxon_rank_uses_names_suffixes_and_depth() -> None:
    assert infer_taxon_rank("Life", {1}) == ("root", "synthetic")
    assert infer_taxon_rank("Plantae", {2}) == ("kingdom", "name")
    assert infer_taxon_rank("Urticaceae", {7}) == ("family", "suffix")
    assert infer_taxon_rank("Rosales", {6}) == ("order", "suffix")
    assert infer_taxon_rank("Urtica", {12}) == ("genus", "path_depth")
