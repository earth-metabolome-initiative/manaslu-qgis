#!/usr/bin/env python3
"""Resolve taxa names from a CSV input with gnverifier."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import mimetypes
import os
import shlex
import subprocess
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterator, TextIO


DEFAULT_INPUT = Path("data/taxa_list/input_taxa_list.csv")
DEFAULT_HEADER = "taxon_name_original"
DEFAULT_RO_CRATE = Path("ro-crate-metadata.json")


def sanitize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = "".join(char if char.isalnum() else "_" for char in ascii_value.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_").lower()


def sniff_dialect(path: Path, delimiter: str | None) -> csv.Dialect:
    if delimiter is not None:
        return type(
            "ExplicitDialect",
            (csv.excel,),
            {"delimiter": delimiter},
        )()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096).lstrip("\r\n")

    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel()


def iter_csv_lines(handle: TextIO) -> Iterator[str]:
    return itertools.dropwhile(lambda line: not line.strip(), handle)


def read_csv_rows(path: Path, delimiter: str | None) -> tuple[list[str], list[dict[str, str]]]:
    dialect = sniff_dialect(path, delimiter)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(iter_csv_lines(handle), dialect=dialect)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {path}")
        headers = list(reader.fieldnames)
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            overflow = row.pop(None, None)
            if overflow and any(value.strip() for value in overflow if value):
                raise ValueError(
                    f"Malformed input CSV at {path}:{row_number}: unexpected extra columns {overflow}"
                )

            normalized_row = {header: (value or "") for header, value in row.items()}
            if not any(value.strip() for value in normalized_row.values()):
                continue
            rows.append(normalized_row)
    return headers, rows


def resolve_header(headers: list[str], requested_header: str) -> str:
    if requested_header in headers:
        return requested_header

    requested_sanitized = sanitize_header(requested_header)
    matches = [header for header in headers if sanitize_header(header) == requested_sanitized]
    if not matches:
        available = ", ".join(headers)
        raise ValueError(
            f"Header '{requested_header}' not found. Available headers: {available}"
        )
    if len(matches) > 1:
        available = ", ".join(matches)
        raise ValueError(
            f"Header '{requested_header}' is ambiguous after normalization. Matches: {available}"
        )
    return matches[0]


def derive_output_path(input_path: Path, suffix: str) -> Path:
    return input_path.with_name(f"{input_path.stem}{suffix}")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def relative_crate_id(path: Path, crate_root: Path) -> str:
    resolved_path = path.resolve()
    resolved_root = crate_root.resolve()
    if resolved_path == resolved_root:
        return "./"
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return resolved_path.as_uri()


def run_command(args: list[str], cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            args,
            check=True,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    output = completed.stdout.strip() or completed.stderr.strip()
    return output or None


def normalize_gnverifier_version(raw_version: str | None) -> str:
    if not raw_version:
        return "unknown"
    for line in raw_version.splitlines():
        line = line.strip()
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip() or "unknown"
    return raw_version.strip() or "unknown"


def file_entity(path: Path, crate_root: Path) -> dict[str, object]:
    relative_id = relative_crate_id(path, crate_root)
    entity: dict[str, object] = {
        "@id": relative_id,
        "@type": "File",
        "name": path.name,
        "contentSize": str(path.stat().st_size),
        "dateModified": datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=datetime.now().astimezone().tzinfo,
        ).isoformat(),
    }
    media_type, _ = mimetypes.guess_type(path.name)
    if media_type:
        entity["encodingFormat"] = media_type
    return entity


def write_ro_crate(
    crate_path: Path,
    input_path: Path,
    names_path: Path,
    results_path: Path,
    merged_path: Path,
    header: str,
    delimiter: str | None,
    dedupe_input: bool,
) -> None:
    crate_root = crate_path.resolve().parent
    crate_root.mkdir(parents=True, exist_ok=True)

    script_path = Path(__file__).resolve()
    readme_path = repo_root() / "README.md"
    now = datetime.now().astimezone().isoformat()
    git_commit = run_command(["git", "rev-parse", "HEAD"], cwd=repo_root())
    gnverifier_version = normalize_gnverifier_version(
        run_command(["gnverifier", "--version"], cwd=repo_root())
    )
    python_version = sys.version.split()[0]
    command = shlex.join([os.path.basename(sys.executable), *sys.argv])

    existing_outputs = [path for path in [names_path, results_path, merged_path] if path.exists()]
    has_part = [input_path, readme_path, script_path, *existing_outputs, crate_path]

    graph: list[dict[str, object]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": [
                {"@id": "https://w3id.org/ro/crate/1.1"},
            ],
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": "manaslu taxa resolution dataset",
            "description": (
                "Manaslu taxa list, derived "
                "gnverifier outputs, and execution provenance for the taxa "
                "resolution workflow."
            ),
            "datePublished": now,
            "hasPart": [{"@id": relative_crate_id(path, crate_root)} for path in has_part],
            "mentions": [
                {"@id": "#resolve-taxa-run"},
                {"@id": "#resolve-taxa-parameters"},
                {"@id": "#resolve-taxa-script"},
                {"@id": "#gnverifier"},
                {"@id": "#python"},
                {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
            ],
            "conformsTo": [
                {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
            ],
        },
        {
            "@id": "#resolve-taxa-script",
            "@type": "SoftwareSourceCode",
            "name": "resolve_taxa.py",
            "programmingLanguage": {"@id": "#python-language"},
            "codeRepository": {"@id": "./"},
            "version": git_commit or "unknown",
            "softwareRequirements": [
                {"@id": "#python"},
                {"@id": "#gnverifier"},
            ],
            "subjectOf": {"@id": relative_crate_id(script_path, crate_root)},
        },
        {
            "@id": "#python-language",
            "@type": "ComputerLanguage",
            "name": "Python",
            "version": python_version,
        },
        {
            "@id": "#python",
            "@type": "SoftwareApplication",
            "name": "Python",
            "version": python_version,
        },
        {
            "@id": "#gnverifier",
            "@type": "SoftwareApplication",
            "name": "gnverifier",
            "version": gnverifier_version,
        },
        {
            "@id": "#resolve-taxa-run",
            "@type": "CreateAction",
            "name": "Resolve taxa names with gnverifier",
            "description": command,
            "endTime": now,
            "instrument": {"@id": "#resolve-taxa-script"},
            "object": [{"@id": relative_crate_id(input_path, crate_root)}],
            "result": [{"@id": relative_crate_id(path, crate_root)} for path in existing_outputs],
            "subjectOf": {"@id": "#resolve-taxa-parameters"},
        },
        {
            "@id": "https://w3id.org/ro/wfrun/process/0.5",
            "@type": "CreativeWork",
            "name": "Process Run Crate profile",
        },
        file_entity(input_path, crate_root),
        file_entity(readme_path, crate_root),
        file_entity(script_path, crate_root),
    ]

    for output_path in existing_outputs:
        graph.append(file_entity(output_path, crate_root))

    graph.append(
        {
            "@id": "#resolve-taxa-parameters",
            "@type": "PropertyValue",
            "name": "resolve_taxa parameters",
            "value": json.dumps(
                {
                    "header": header,
                    "delimiter": delimiter,
                    "dedupe_input": dedupe_input,
                },
                sort_keys=True,
            ),
        }
    )

    crate = {
        "@context": [
            "https://w3id.org/ro/crate/1.1/context",
            "https://w3id.org/ro/terms/workflow-run/context",
        ],
        "@graph": graph,
    }

    with crate_path.open("w", encoding="utf-8") as handle:
        json.dump(crate, handle, indent=2)
        handle.write("\n")


def build_query_plan(
    rows: list[dict[str, str]],
    header: str,
    dedupe_input: bool,
) -> tuple[list[str], list[int | None]]:
    query_names: list[str] = []
    query_index_by_name: dict[str, int] = {}
    row_query_indexes: list[int | None] = []

    for row in rows:
        taxon_name = row.get(header, "").strip()
        if not taxon_name:
            row_query_indexes.append(None)
            continue

        if dedupe_input and taxon_name in query_index_by_name:
            row_query_indexes.append(query_index_by_name[taxon_name])
            continue

        query_index = len(query_names)
        query_names.append(taxon_name)
        query_index_by_name[taxon_name] = query_index
        row_query_indexes.append(query_index)

    return query_names, row_query_indexes


def write_names(names: list[str], dest: Path, force: bool) -> None:
    if dest.exists() and not force:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as handle:
        for name in names:
            handle.write(f"{name}\n")


def run_gnverifier(names_path: Path, results_path: Path, force: bool) -> None:
    if results_path.exists() and not force:
        return
    results_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with results_path.open("w", encoding="utf-8", newline="") as handle:
            subprocess.run(
                ["gnverifier", "-f", "csv", "--quiet", str(names_path)],
                check=True,
                stdout=handle,
            )
    except FileNotFoundError as exc:
        raise SystemExit(
            "gnverifier is not available on PATH. Install it or rerun with --skip-gnverifier."
        ) from exc


def read_gnverifier_results(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            overflow = row.pop(None, None)
            if overflow:
                raise ValueError(
                    f"Malformed gnverifier CSV at {path}:{row_number}: unexpected extra columns {overflow}"
                )
            rows.append(row)
    return headers, rows


def merge_results(
    headers: list[str],
    rows: list[dict[str, str]],
    row_query_indexes: list[int | None],
    result_headers: list[str],
    result_rows: list[dict[str, str]],
    merged_path: Path,
    force: bool,
) -> None:
    if merged_path.exists() and not force:
        return
    merged_path.parent.mkdir(parents=True, exist_ok=True)

    merged_headers = headers + [header for header in result_headers if header not in headers]
    empty_result = {header: "" for header in result_headers}

    with merged_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=merged_headers)
        writer.writeheader()
        for row, query_index in zip(rows, row_query_indexes):
            result_row = empty_result if query_index is None else result_rows[query_index]
            writer.writerow({**row, **result_row})


def align_result_rows(
    query_names: list[str],
    result_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    results_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    missing_scientific_name = 0

    for result_row in result_rows:
        scientific_name = (result_row.get("ScientificName") or "").strip()
        if not scientific_name:
            missing_scientific_name += 1
            continue
        results_by_name[scientific_name].append(result_row)

    if missing_scientific_name:
        raise ValueError(
            f"gnverifier returned {missing_scientific_name} rows without a ScientificName value"
        )

    aligned_rows: list[dict[str, str]] = []
    missing_queries: list[str] = []
    for query_name in query_names:
        matches = results_by_name.get(query_name)
        if not matches:
            missing_queries.append(query_name)
            if len(missing_queries) >= 5:
                break
            continue
        aligned_rows.append(matches.pop())

    if missing_queries:
        details = ", ".join(repr(name) for name in missing_queries)
        raise ValueError(
            "gnverifier results could not be matched back to the input names. "
            f"Examples: {details}"
        )

    leftover_names = [name for name, matches in results_by_name.items() if matches]
    if leftover_names:
        details = ", ".join(repr(name) for name in leftover_names[:5])
        raise ValueError(
            "gnverifier returned extra rows that were not matched to the input names. "
            f"Examples: {details}"
        )

    return aligned_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="Input CSV path",
    )
    parser.add_argument(
        "--header",
        default=DEFAULT_HEADER,
        help="CSV column containing the input taxon names",
    )
    parser.add_argument(
        "--delimiter",
        help="CSV delimiter override. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--names",
        help="Output path for the taxa names text file",
    )
    parser.add_argument(
        "--results",
        help="Output path for gnverifier CSV results",
    )
    parser.add_argument(
        "--merged",
        help="Output path for merged CSV results",
    )
    parser.add_argument(
        "--dedupe-input",
        action="store_true",
        help="Query each unique taxon name once and reuse the result for duplicates",
    )
    parser.add_argument(
        "--skip-gnverifier",
        action="store_true",
        help="Only extract the taxa names file and skip gnverifier execution",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing derived files",
    )
    parser.add_argument(
        "--ro-crate",
        default=str(DEFAULT_RO_CRATE),
        help="Output path for the RO-Crate metadata file",
    )
    parser.add_argument(
        "--skip-ro-crate",
        action="store_true",
        help="Do not generate RO-Crate metadata",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    names_path = Path(args.names) if args.names else derive_output_path(input_path, "_names.txt")
    results_path = (
        Path(args.results)
        if args.results
        else derive_output_path(input_path, "_gnverifier.csv")
    )
    merged_path = (
        Path(args.merged)
        if args.merged
        else derive_output_path(input_path, "_resolved.csv")
    )
    crate_path = Path(args.ro_crate)

    headers, rows = read_csv_rows(input_path, args.delimiter)
    header = resolve_header(headers, args.header)
    query_names, row_query_indexes = build_query_plan(rows, header, args.dedupe_input)
    write_names(query_names, names_path, args.force)

    if args.skip_gnverifier:
        if not args.skip_ro_crate:
            write_ro_crate(
                crate_path,
                input_path,
                names_path,
                results_path,
                merged_path,
                header,
                args.delimiter,
                args.dedupe_input,
            )
        return 0

    if not query_names:
        merge_results(headers, rows, row_query_indexes, [], [], merged_path, args.force)
        if not args.skip_ro_crate:
            write_ro_crate(
                crate_path,
                input_path,
                names_path,
                results_path,
                merged_path,
                header,
                args.delimiter,
                args.dedupe_input,
            )
        return 0

    run_gnverifier(names_path, results_path, args.force)
    result_headers, result_rows = read_gnverifier_results(results_path)

    if len(result_rows) != len(query_names):
        raise ValueError(
            f"Row count mismatch: {len(query_names)} queried names vs {len(result_rows)} gnverifier rows"
        )
    result_rows = align_result_rows(query_names, result_rows)

    merge_results(
        headers,
        rows,
        row_query_indexes,
        result_headers,
        result_rows,
        merged_path,
        args.force,
    )
    if not args.skip_ro_crate:
        write_ro_crate(
            crate_path,
            input_path,
            names_path,
            results_path,
            merged_path,
            header,
            args.delimiter,
            args.dedupe_input,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
