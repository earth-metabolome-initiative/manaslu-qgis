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
- Map layer: `qgis/manaslu/optimized_maps/Manaslu-EMI.kml`

## QField conventions

- The active observation layer follows the same schema as `jbn-new`.
- Sample identifiers must match `dbgi_######`.
- QField image paths are generated from the sample identifier only, for example
  `DCIM/manaslu/dbgi_001234_01.jpg`.
- Taxon names are used for lookup/display fields, but not for image naming.
- `uuid_qfield` is generated automatically with QGIS `uuid('WithoutBraces')`.

## Source map

The map layer was copied from `/Users/pma/Downloads/Manaslu-EMI.kml` and added
as the single layer in the project `map` group.

## Taxonomic resolution

Taxa are resolved with `gnverifier` via:

```bash
python3 scripts/resolve_taxa.py --force --header taxon_name --dedupe-input
ogr2ogr -f GPKG qgis/manaslu/species_list.gpkg qgis/manaslu/species_list.csv -nln species_list -nlt NONE -overwrite -oo EMPTY_STRING_AS_NULL=YES
```

The workflow writes:

- `data/taxa_list/input_taxa_list_names.txt`
- `data/taxa_list/input_taxa_list_gnverifier.csv`
- `data/taxa_list/input_taxa_list_resolved.csv`

`qgis/manaslu/species_list.csv` and `qgis/manaslu/species_list.gpkg` are built
from the resolved CSV so QField can populate `MatchedCanonical` and `TaxonId`.
