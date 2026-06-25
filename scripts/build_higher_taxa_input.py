#!/usr/bin/env python3
"""Build a higher-taxa input CSV from resolved species ClassificationPath values."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


DEFAULT_INPUT = Path("data/inaturalist/nepal_species_observations_resolved.csv")
DEFAULT_OUTPUT = Path("data/inaturalist/nepal_higher_taxa.csv")
DEFAULT_CLASSIFICATION_HEADER = "ClassificationPath"
DEFAULT_NAME_HEADERS = ("ScientificName", "MatchedCanonical", "scientific_name")
DEFAULT_EXCLUDED_TAXA = frozenset({"sect."})

OUTPUT_FIELDS = [
    "scientific_name",
    "taxon_level",
    "taxon_rank",
    "taxon_rank_source",
    "source_species_count",
    "path_depth_min",
    "path_depth_max",
    "example_species",
    "example_classification_path",
]


@dataclass
class HigherTaxonSummary:
    name: str
    source_species: set[str]
    path_depths: set[int]
    example_species: str
    example_classification_path: str


def split_classification_path(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def first_present(row: dict[str, str], headers: Iterable[str]) -> str:
    for header in headers:
        value = (row.get(header) or "").strip()
        if value:
            return value
    return ""


def infer_taxon_rank(name: str, depths: set[int]) -> tuple[str, str]:
    """Infer a useful rank label from common names/suffixes and path position."""
    lower_name = name.casefold()
    if lower_name == "life":
        return "root", "synthetic"
    if lower_name in {"eukaryota", "bacteria", "archaea"}:
        return "domain", "name"
    if lower_name in {"animalia", "plantae", "fungi", "chromista", "protozoa"}:
        return "kingdom", "name"

    suffix_rules = [
        ("family", ("aceae", "idae")),
        ("subfamily", ("oideae", "inae")),
        ("tribe", ("eae", "ini")),
        ("order", ("ales", "formes")),
        ("class", ("opsida", "phyceae", "mycetes")),
        ("phylum", ("phyta", "mycota")),
    ]
    for rank, suffixes in suffix_rules:
        if any(lower_name.endswith(suffix) for suffix in suffixes):
            return rank, "suffix"

    if max(depths) >= 4:
        return "genus", "path_depth"
    return "higher_taxon", "fallback"


def iter_higher_taxa(
    rows: Iterable[dict[str, str]],
    *,
    classification_header: str,
    name_headers: Iterable[str],
    include_life: bool,
    excluded_taxa: set[str] | frozenset[str] = DEFAULT_EXCLUDED_TAXA,
) -> dict[str, HigherTaxonSummary]:
    rows = list(rows)
    source_species_names = {
        first_present(row, name_headers).casefold()
        for row in rows
        if first_present(row, name_headers)
    }
    excluded_names = {name.casefold() for name in excluded_taxa} | source_species_names
    summaries: dict[str, HigherTaxonSummary] = {}
    source_counts_by_taxon: dict[str, set[str]] = defaultdict(set)
    depths_by_taxon: dict[str, set[int]] = defaultdict(set)

    for row in rows:
        classification_path = (row.get(classification_header) or "").strip()
        path_parts = split_classification_path(classification_path)
        species_name = first_present(row, name_headers)
        if not path_parts or not species_name:
            continue

        if path_parts[-1].casefold() == species_name.casefold():
            ancestors = path_parts[:-1]
        else:
            ancestors = path_parts
        if include_life:
            ancestors = ["Life", *ancestors]

        for depth, name in enumerate(ancestors, start=1):
            if name.casefold() in excluded_names:
                continue
            source_counts_by_taxon[name].add(species_name)
            depths_by_taxon[name].add(depth)
            if name not in summaries:
                summaries[name] = HigherTaxonSummary(
                    name=name,
                    source_species=set(),
                    path_depths=set(),
                    example_species=species_name,
                    example_classification_path=classification_path,
                )

    for name, summary in summaries.items():
        summary.source_species = source_counts_by_taxon[name]
        summary.path_depths = depths_by_taxon[name]
    return summaries


def summary_to_row(summary: HigherTaxonSummary) -> dict[str, str]:
    taxon_rank, taxon_rank_source = infer_taxon_rank(summary.name, summary.path_depths)
    return {
        "scientific_name": summary.name,
        "taxon_level": "higher_taxon",
        "taxon_rank": taxon_rank,
        "taxon_rank_source": taxon_rank_source,
        "source_species_count": str(len(summary.source_species)),
        "path_depth_min": str(min(summary.path_depths)),
        "path_depth_max": str(max(summary.path_depths)),
        "example_species": summary.example_species,
        "example_classification_path": summary.example_classification_path,
    }


def sorted_summary_rows(summaries: dict[str, HigherTaxonSummary]) -> list[dict[str, str]]:
    return [
        summary_to_row(summary)
        for summary in sorted(
            summaries.values(),
            key=lambda item: (
                min(item.path_depths),
                item.name.casefold(),
            ),
        )
    ]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Resolved species CSV")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Higher-taxa CSV output. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--classification-header",
        default=DEFAULT_CLASSIFICATION_HEADER,
        help="Column containing pipe-delimited gnverifier classification paths.",
    )
    parser.add_argument(
        "--name-header",
        action="append",
        default=None,
        help=(
            "Species name column to use when removing the terminal species from "
            "ClassificationPath. May be repeated."
        ),
    )
    parser.add_argument(
        "--exclude-life",
        action="store_true",
        help="Do not add the synthetic root taxon 'Life'.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_csv(args.input)
    summaries = iter_higher_taxa(
        rows,
        classification_header=args.classification_header,
        name_headers=args.name_header or DEFAULT_NAME_HEADERS,
        include_life=not args.exclude_life,
    )
    output_rows = sorted_summary_rows(summaries)
    write_csv(args.output, output_rows)
    print(f"Wrote {len(output_rows)} higher taxa to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
