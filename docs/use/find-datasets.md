# Find datasets

## On HDX

Every country and layer is one dataset on the
[HOT organisation page](https://data.humdata.org/organization/hot). Dataset names follow
one pattern, so a URL can be written without searching:

```text
https://data.humdata.org/dataset/hotosm_<iso3>_<layer>
```

For example, the buildings of Nepal are at
[hotosm_npl_buildings](https://data.humdata.org/dataset/hotosm_npl_buildings). The layer
names are listed in [What the exports contain](../reference/contents.md).

Each dataset page offers the files for download and links to a report page with a map,
the attributes and how complete they are.

## In the STAC catalog

The [STAC](https://stacspec.org/) catalog indexes the same layers. It is static JSON,
readable by any STAC client without an account.

The root catalog is:

```text
https://production-raw-data-api.s3.amazonaws.com/ISO3/catalog.json
```

It is organised in four levels:

| Level | Example | Holds |
| --- | --- | --- |
| Root catalog | `ISO3/catalog.json` | One child catalog per country. |
| Country catalog | `ISO3/NPL/catalog.json` | One collection per layer of that country. |
| Collection | `ISO3/NPL/buildings/hotosm_npl_buildings_osm_metadata.json` | The layer's description, licence, extent and a link to its HDX dataset. |
| Item | `ISO3/NPL/buildings/hotosm_npl_buildings_osm_item.json` | The files (assets) of the latest export, and the columns of the data. |

The item's assets are the files you load or download.

## In STAC Browser

[STAC Browser](https://radiantearth.github.io/stac-browser/#/external/production-raw-data-api.s3.amazonaws.com/ISO3/catalog.json)
shows the catalog as web pages. Pick a country, then a layer, then the item, to see its
extent on a map, its columns and a download link for each file.

## Check when a dataset was last updated

The [update status page](https://hotosm.github.io/hot2hdx-status/) lists every HOT
dataset on HDX with its update frequency, last update and due date, and marks it outdated,
due soon (within seven days) or up to date. Pick a country, then click a dataset to open
it on HDX.
