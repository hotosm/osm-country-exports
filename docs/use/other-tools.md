# Other tools

## GDAL and ogr2ogr

GDAL reads the GeoParquet and PMTiles files over HTTP when the URL is prefixed with
`/vsicurl/`. `ogr2ogr` can then cut out an area with `-spat`, given as
`xmin ymin xmax ymax` in longitude and latitude, and write it to any format GDAL supports:

```bash
ogr2ogr -f GPKG kathmandu_health.gpkg \
  /vsicurl/https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/_layers/osm/health_facilities.parquet \
  -spat 85.25 27.65 85.40 27.75
```

`ogrinfo` lists a file's layers, columns and feature count without downloading it:

```bash
ogrinfo -so -al /vsicurl/https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/_layers/osm/airports.parquet
```

## Python with pystac

[pystac](https://pystac.readthedocs.io/) walks the catalog. Country catalogs are named
`hotosm_<iso3>` and layer collections `hotosm_<iso3>_<layer>`:

```python
import pystac

catalog = pystac.Catalog.from_file(
    "https://production-raw-data-api.s3.amazonaws.com/ISO3/catalog.json"
)
nepal = catalog.get_child("hotosm_npl")
health = nepal.get_child("hotosm_npl_health_facilities")
item = next(health.get_items())
print(item.datetime, item.assets["geoparquet"].href)
```

The asset URL can then be read with DuckDB, GeoPandas or any library that reads
GeoParquet. The [DuckDB page](duckdb.md) shows how to filter it by area.

## Direct downloads

Every file in the catalog is a plain HTTPS URL, so `curl`, `wget` or a web browser can
download it. The download links on HDX point to the same files.
