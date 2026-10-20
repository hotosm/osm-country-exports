# HOT country exports

The Humanitarian OpenStreetMap Team (HOT) publishes OpenStreetMap data for every country as
ready-to-use GIS layers: buildings, roads, waterways, health and education facilities, and
more. Most countries are rebuilt monthly, as set out in [The schedule](reference/schedule.md),
and every layer is published on HDX and in a STAC catalog.

| Where | What it is for |
| --- | --- |
| [HDX](https://data.humdata.org/organization/hot) | One dataset per country and layer, with downloads in common GIS formats. |
| [STAC catalog](https://production-raw-data-api.s3.amazonaws.com/ISO3/catalog.json) | A machine-readable index of every layer, for QGIS, scripts and cloud-native tools. |
| [STAC Browser](https://radiantearth.github.io/stac-browser/#/external/production-raw-data-api.s3.amazonaws.com/ISO3/catalog.json) | The same catalog as web pages, for browsing in a web browser. |

The [update status page](https://hotosm.github.io/hot2hdx-status/) shows when each dataset
was last updated on HDX and when the next update is due.

## Use the data

- [Find datasets](use/find-datasets.md) on HDX, in the STAC catalog or in STAC Browser.
- [Open them in QGIS](use/qgis.md), straight from the catalog.
- [Query them with DuckDB](use/duckdb.md), including cutting out one area without
  downloading a whole country.
- [Use other tools](use/other-tools.md) such as GDAL and Python.

## Reference

- [What the exports contain](reference/contents.md): layers, formats, columns and file names.
- [The schedule](reference/schedule.md): which countries are updated, and how often.

## Maintain the exports

- [Edit a country](maintain/edit-a-country.md)
- [Add an event](maintain/add-an-event.md)
- [Run and operate](maintain/operate.md)

The exports are built by [oex](https://github.com/osgeonepal/oex). This repository holds
the configuration, the schedule and the scripts that run it.
