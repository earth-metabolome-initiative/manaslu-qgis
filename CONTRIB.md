# Contributing to the Manaslu QField Project

## Updating the field polygon

The QGIS project loads the field polygon from:

- Source KML: `qgis/manaslu/optimized_maps/Manaslu-EMI.kml`
- QGIS layer: `qgis/manaslu/optimized_maps/Manaslu-EMI.gpkg`

When Google Earth exports a new polygon, replace the source KML and regenerate
the GeoPackage layer without changing the layer name used by the QGIS project:

```bash
cp /path/to/new-polygon.kml qgis/manaslu/optimized_maps/Manaslu-EMI.kml
ogr2ogr -f GPKG \
  qgis/manaslu/optimized_maps/Manaslu-EMI.gpkg \
  qgis/manaslu/optimized_maps/Manaslu-EMI.kml \
  -nln Manaslu_EMI \
  -overwrite
```

Open `qgis/manaslu/manaslu.qgs` in QGIS and confirm the `Manaslu-EMI` layer
appears in the `map` group, has one polygon feature, and covers the intended
field area.

## Exporting a basemap and polygon to QField

1. Export the polygon from Google Earth as KML.
   Save the polygon from Google Earth as a KML file, replace
   `qgis/manaslu/optimized_maps/Manaslu-EMI.kml`, and regenerate
   `Manaslu-EMI.gpkg` with the command above.

2. Open the project in QGIS.
   Open `qgis/manaslu/manaslu.qgs`, check that the `Manaslu-EMI` polygon and
   the satellite basemap line up.

3. Align the polygon with the Google Earth basemap.
   Add the Google Earth or Google satellite imagery basemap in QGIS, zoom to
   the `Manaslu-EMI` polygon, and visually confirm that the polygon boundary
   matches the intended area from Google Earth. If the boundary is wrong, fix it
   in Google Earth, export a new KML, and regenerate `Manaslu-EMI.gpkg` before
   continuing.

4. Create the offline basemap from the QField project options.
   In QGIS, open `Project > Properties > QField`. In the `Area of interest`
   options, set the area to the `Manaslu-EMI` polygon extent. In the `Base map`
   options, create/update the offline basemap from the Google imagery layer with
   minimum zoom `14` and maximum zoom `17`.

5. Package the project for QField/QFieldCloud.
   In the QField packaging actions, include the generated basemap and keep the
   reference layers as copy/synchronize layers. The editable `observations`
   layer should remain configured for offline editing. Package/export the
   project to:

   ```text
   /Users/pma/QField/export/manaslu
   ```

6. Prune and move the exported basemap back into the repository.
   The QField export writes the generated rectangular basemap at the export
   root. Prune it against the `Manaslu-EMI` polygon before replacing the
   repository basemap, so the MBTiles file follows the polygon tile footprint
   as closely as possible:

   ```bash
   python3 scripts/prune_mbtiles_to_polygon.py \
     --mbtiles /Users/pma/QField/export/manaslu/basemap.mbtiles \
     --polygon qgis/manaslu/optimized_maps/Manaslu-EMI.kml \
     --output qgis/manaslu/optimized_maps/basemap.mbtiles \
     --buffer-tiles 1 \
     --force
   ```

   Keep the destination filename as `basemap.mbtiles`, because
   `qgis/manaslu/manaslu.qgs` points the `basemap` layer at
   `qgis/manaslu/optimized_maps/basemap.mbtiles`. The `--buffer-tiles 1`
   option keeps one tile of breathing room around the polygon so QField does
   not show blank edges when panning near the boundary.

   If the exported polygon files were also changed during packaging, copy them
   to:

   ```text
   /Users/pma/QField/export/manaslu/optimized_maps/Manaslu-EMI.kml
   -> qgis/manaslu/optimized_maps/Manaslu-EMI.kml

   /Users/pma/QField/export/manaslu/optimized_maps/Manaslu-EMI.gpkg
   -> qgis/manaslu/optimized_maps/Manaslu-EMI.gpkg
   ```

7. Verify the packaged project.
   Upload or synchronize the project with QFieldCloud, then open it in QField
   and confirm that the basemap, polygon, lookup tables, and observation form
   work as expected.
