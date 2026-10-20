# Query the data with DuckDB

[DuckDB](https://duckdb.org/) reads the GeoParquet files straight from their URLs, so you
can count, filter and cut out an area without downloading a whole country. The examples
use the DuckDB command line, and the same SQL runs from Python, R or any DuckDB client.

Every layer's GeoParquet file has a URL of this form:

```text
https://production-raw-data-api.s3.amazonaws.com/ISO3/<ISO3>/_layers/osm/<layer>.parquet
```

The URL is also listed as the `geoparquet` asset of each item in the
[STAC catalog](find-datasets.md#in-the-stac-catalog).

## Set up

Install DuckDB from [duckdb.org](https://duckdb.org/docs/installation/), start it, and
load the spatial extension once per session:

```sql
INSTALL spatial;
LOAD spatial;
```

DuckDB loads its HTTP support by itself the first time a query reads an `https://` URL.

## See what a layer holds

```sql
DESCRIBE SELECT *
FROM 'https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/_layers/osm/health_facilities.parquet';
```

```sql
SELECT count(*)
FROM 'https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/_layers/osm/buildings.parquet';
```

The columns are described in [What the exports contain](../reference/contents.md#columns).

## Cut out one area

Each row has a `bbox` column holding the bounding box of its geometry, with the fields
`xmin`, `ymin`, `xmax` and `ymax` in longitude and latitude. Filter on it to keep one
area:

```sql
SELECT id, name, building, building_levels, geom
FROM 'https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/_layers/osm/buildings.parquet'
WHERE bbox.xmin >= 85.30 AND bbox.xmax <= 85.34
  AND bbox.ymin >= 27.69 AND bbox.ymax <= 27.72;
```

This box covers central Kathmandu and returns about 47,000 buildings out of more than
eight million in Nepal. The condition keeps features that lie entirely inside the box. To
also keep features that cross its edge, test for overlap:

```sql
WHERE bbox.xmax >= 85.30 AND bbox.xmin <= 85.34
  AND bbox.ymax >= 27.69 AND bbox.ymin <= 27.72
```

To cut along an exact boundary, filter on the box first and then test
the geometry, so the precise test only runs on the rows the box keeps:

```sql
WHERE bbox.xmax >= 85.30 AND bbox.xmin <= 85.34
  AND bbox.ymax >= 27.69 AND bbox.ymin <= 27.72
  AND ST_Intersects(geom, ST_GeomFromText('POLYGON((85.30 27.69, 85.34 27.69, 85.34 27.72, 85.30 27.72, 85.30 27.69))'))
```

## Filter by attributes or by administrative area

Every layer carries the codes and names of the administrative areas each feature falls
in, so you can select a province or district without drawing a boundary:

```sql
SELECT adm2_name, count(*) AS facilities
FROM 'https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/_layers/osm/health_facilities.parquet'
GROUP BY adm2_name
ORDER BY facilities DESC;
```

## Save the result

`COPY` writes a query's result to a file that QGIS and other GIS tools open directly:

```sql
COPY (
  SELECT name, amenity, healthcare, geom
  FROM 'https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/_layers/osm/health_facilities.parquet'
  WHERE bbox.xmin >= 85.25 AND bbox.xmax <= 85.40
    AND bbox.ymin >= 27.65 AND bbox.ymax <= 27.75
) TO 'kathmandu_health.geojson' WITH (FORMAT GDAL, DRIVER 'GeoJSON');
```

Change the file name and `DRIVER` to write another format, for example
`'kathmandu_buildings.gpkg'` with `DRIVER 'GPKG'` for a GeoPackage.
