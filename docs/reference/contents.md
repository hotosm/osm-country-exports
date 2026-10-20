# What the exports contain

## Layers

Every country has the same twelve layers. Each is one HDX dataset, named
`hotosm_<iso3>_<layer>`, and one collection in the STAC catalog.

| Layer | HDX title | Main OpenStreetMap tags |
| --- | --- | --- |
| `buildings` | Buildings | `building` |
| `roads` | Roads | `highway` |
| `waterways` | Waterways | `waterway`, `water`, `natural` |
| `railways` | Railways | `railway` |
| `education_facilities` | Education Facilities | `amenity`, `building` |
| `health_facilities` | Health Facilities | `amenity`, `healthcare` |
| `populated_places` | Populated Places | `place`, `landuse` |
| `financial_services` | Financial Services | `amenity` |
| `airports` | Airports | `aeroway`, `building`, `emergency` |
| `sea_ports` | Sea Ports | `industrial=port`, `harbour`, `port` and related tags |
| `points_of_interest` | Points of Interest | `amenity`, `shop`, `tourism`, `man_made` and related tags |
| `cultural_places` | Cultural Places | `tourism`, `amenity`, `historic`, `heritage` and related tags |

The exact tag filters and columns of each layer are defined in
[`configs/_hot-schema.yaml`](https://github.com/hotosm/osm-country-exports/blob/main/configs/_hot-schema.yaml).

## Formats

| Format | Buildings and roads | Other layers | Notes |
| --- | --- | --- | --- |
| GeoPackage | yes | yes | Zipped. |
| Shapefile | yes | yes | Zipped. Left out when the write fails, for example past the format's 4 GB limit. |
| GeoJSON | no | yes | Zipped. |
| KML | no | yes | Zipped. |
| GeoParquet | yes | yes | Not zipped, so tools can read it over HTTP. |
| PMTiles | yes | yes | Vector tiles for display, simplified at lower zooms. |

Each dataset also has:

- a **report page** (`..._report.html`) with a map, the attributes, how complete each one
  is, and the administrative areas covered;
- a **STAC collection** (`..._osm_metadata.json`) describing the layer, which links to the
  item holding the files.

## Columns

Every layer has these columns, alongside the OpenStreetMap tags it selects:

| Column | Holds |
| --- | --- |
| `id` | The OpenStreetMap element, such as `node/9790076524` or `way/123456`. |
| `name` | The `name` tag. |
| `name_en`, `name_<local language>` | Names in English and the country's own languages, where mapped. |
| `name_latin` | A name in Latin script: `name_en` where present, otherwise `name` transliterated. |
| `adm0_pcode` to `adm4_pcode`, `adm0_name` to `adm4_name` | The administrative areas the feature falls in, from the [fieldmaps.io](https://fieldmaps.io/) humanitarian boundaries. Empty for levels a country does not have. |
| `bbox` | The bounding box of the geometry (`xmin`, `ymin`, `xmax`, `ymax`), used to [filter by area](../use/duckdb.md#cut-out-one-area). GeoParquet only. |
| `geom` | The geometry, in longitude and latitude (EPSG:4326). |

Most tag columns use the tag name with `:` replaced by `_`, so `building:levels` becomes
`building_levels`.

## Licence

The data is from OpenStreetMap and is published under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
Credit "OpenStreetMap contributors" when you use it.
