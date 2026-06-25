# Manaslu QField project

Project code: `manaslu`

This repository contains the QGIS/QField project for the EMI Manaslu mission,
following the `jbn-new` project structure.

## Main files

- QGIS/QField project: `qgis/manaslu/manaslu.qgs`
- Active observation layer: `qgis/manaslu/observations.gpkg`
- Species lookup: `qgis/manaslu/species_list.gpkg`
- Collector lookup: `qgis/manaslu/collector_list.gpkg`
- Observation subject lookup: `qgis/manaslu/observation_subject.gpkg`
- Map polygon: `qgis/manaslu/optimized_maps/Manaslu-EMI.gpkg`
- Offline basemap: `qgis/manaslu/optimized_maps/basemap.mbtiles`

## QField conventions

- The active observation layer follows the same schema as `jbn-new`.
- Sample identifiers must match `dbgi_######`.
- QField image paths are generated from the sample identifier only, for example
  `DCIM/manaslu/dbgi_001234_01.jpg`.
- Taxon names are used for lookup/display fields, but not for image naming.
- `uuid_qfield` is generated automatically with QGIS `uuid('WithoutBraces')`.

## Source map

The source polygon was copied from `/Users/pma/Downloads/Manaslu-EMI-red.kml`,
converted to GeoPackage, and added to the project `map` group. The offline
satellite basemap is stored as an MBTiles file in `optimized_maps/` so QFieldSync
can transfer it with the project.

## Taxonomic resolution

The active QField species lookup is built from the Nepal-wide iNaturalist
species export plus higher taxa derived from the gnverifier classification
paths. Taxa are resolved with `gnverifier` via:

```bash
uv run python scripts/resolve_taxa.py \
  --input data/inaturalist/nepal_species_observations.csv \
  --header scientific_name \
  --dedupe-input \
  --force

python3 scripts/build_higher_taxa_input.py \
  --input data/inaturalist/nepal_species_observations_resolved.csv \
  --output data/inaturalist/nepal_higher_taxa.csv

python3 scripts/resolve_taxa.py \
  --input data/inaturalist/nepal_higher_taxa.csv \
  --header scientific_name \
  --dedupe-input \
  --force \
  --ro-crate data/inaturalist/nepal_higher_taxa_ro-crate-metadata.json

python3 scripts/combine_species_and_higher_taxa.py \
  --species data/inaturalist/nepal_species_observations_resolved.csv \
  --higher-taxa data/inaturalist/nepal_higher_taxa_resolved.csv \
  --output qgis/manaslu/species_list.csv

ogr2ogr -f GPKG qgis/manaslu/species_list.gpkg qgis/manaslu/species_list.csv -nln species_list -nlt NONE -overwrite -oo EMPTY_STRING_AS_NULL=YES
```

The workflow writes:

- `data/inaturalist/nepal_species_observations_names.txt`
- `data/inaturalist/nepal_species_observations_gnverifier.csv`
- `data/inaturalist/nepal_species_observations_resolved.csv`
- `data/inaturalist/nepal_higher_taxa.csv`
- `data/inaturalist/nepal_higher_taxa_gnverifier.csv`
- `data/inaturalist/nepal_higher_taxa_resolved.csv`

`qgis/manaslu/species_list.csv` and `qgis/manaslu/species_list.gpkg` are built
from the combined resolved CSV so QField can populate `MatchedCanonical` and
`TaxonId`. The combined lookup includes a `lookup_type` field with `species` or
`higher_taxon`, plus `taxon_rank` and `taxon_rank_source` fields. Species ranks
come from iNaturalist; higher-taxon ranks are inferred from known names,
taxonomic suffixes, and classification-path position.

## iNaturalist regional species

Candidate species observed around the Manaslu field polygon can be fetched from
iNaturalist with `pyinaturalist`. The query uses the bounding box of
`qgis/manaslu/optimized_maps/Manaslu-EMI.gpkg`, because the iNaturalist species
counts endpoint accepts rectangular spatial filters.

Install dependencies and run:

```bash
uv sync
uv run python scripts/fetch_inaturalist_species.py
```

The default output is:

- `data/inaturalist/manaslu_species_observations.csv`
- `data/inaturalist/manaslu_species_observations.metadata.txt`

Useful variants:

```bash
# Plant-only list for collection planning
uv run python scripts/fetch_inaturalist_species.py --iconic-taxa Plantae

# Restrict to research-grade records only
uv run python scripts/fetch_inaturalist_species.py --quality-grade research

# Search another rectangular area
uv run python scripts/fetch_inaturalist_species.py \
  --south 28.55 --west 84.60 --north 28.70 --east 84.82 \
  --output data/inaturalist/another_area_species.csv

# Equivalent compact form: south,west,north,east
uv run python scripts/fetch_inaturalist_species.py \
  --bbox 28.30,84.29,28.40,84.57

# Search all species observed in Nepal by ISO country code
uv run python scripts/fetch_inaturalist_species.py \
  --country-code NP \
  --output data/inaturalist/nepal_species_observations.csv

# Search by known iNaturalist place ID directly
uv run python scripts/fetch_inaturalist_species.py \
  --place-id 7335 \
  --output data/inaturalist/nepal_species_observations.csv

# Quick smoke run while developing
uv run python scripts/fetch_inaturalist_species.py --max-pages 1
```

The CSV includes iNaturalist taxon IDs, scientific names, common names, broad
taxon group, regional observation counts, global observation counts, and a
representative photo URL/license when available.

To find coordinates in Google Maps, right-click the southwest corner of your
desired search rectangle and copy the latitude/longitude shown in the menu; use
those as `--south` and `--west`. Then right-click the northeast corner and use
those values as `--north` and `--east`. Google Maps shows coordinates as
`latitude, longitude`.

For country-wide searches, use ISO 3166-1 country codes such as `NP` or `NPL`
for Nepal. The script resolves the code to an iNaturalist place ID before
querying observations.
