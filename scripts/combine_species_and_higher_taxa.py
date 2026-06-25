#!/usr/bin/env python3
"""Combine resolved species and resolved higher taxa into one QField lookup CSV."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


DEFAULT_SPECIES = Path("data/inaturalist/nepal_species_observations_resolved.csv")
DEFAULT_HIGHER_TAXA = Path("data/inaturalist/nepal_higher_taxa_resolved.csv")
DEFAULT_OUTPUT = Path("qgis/manaslu/species_list.csv")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def union_headers(*header_lists: list[str]) -> list[str]:
    headers: list[str] = []
    seen: set[str] = set()
    preferred_prefix = ["lookup_type"]
    for header in preferred_prefix:
        headers.append(header)
        seen.add(header)
    for header_list in header_lists:
        for header in header_list:
            if header not in seen:
                headers.append(header)
                seen.add(header)
    return headers


def add_lookup_type(rows: list[dict[str, str]], lookup_type: str) -> list[dict[str, str]]:
    typed_rows: list[dict[str, str]] = []
    for row in rows:
        typed_row = {**row, "lookup_type": lookup_type}
        if lookup_type == "species":
            typed_row["taxon_rank"] = row.get("rank") or "species"
            typed_row["taxon_rank_source"] = "inaturalist"
        typed_rows.append(typed_row)
    return typed_rows


def sort_lookup_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    type_order = {"higher_taxon": 0, "species": 1}
    return sorted(
        rows,
        key=lambda row: (
            type_order.get(row.get("lookup_type", ""), 9),
            row.get("ScientificName") or row.get("scientific_name") or "",
        ),
    )


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--species", type=Path, default=DEFAULT_SPECIES)
    parser.add_argument("--higher-taxa", type=Path, default=DEFAULT_HIGHER_TAXA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    species_headers, species_rows = read_csv(args.species)
    higher_headers, higher_rows = read_csv(args.higher_taxa)
    headers = union_headers(species_headers, higher_headers)
    rows = sort_lookup_rows(
        [
            *add_lookup_type(higher_rows, "higher_taxon"),
            *add_lookup_type(species_rows, "species"),
        ]
    )
    write_csv(args.output, headers, rows)
    print(
        f"Wrote {len(rows)} lookup rows to {args.output} "
        f"({len(higher_rows)} higher taxa, {len(species_rows)} species)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
