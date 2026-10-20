# Edit a country

Every country starts from
[`configs/base.yaml`](https://github.com/hotosm/osm-country-exports/blob/main/configs/base.yaml),
which holds the HDX, S3 and output settings, and the layers in
[`configs/_hot-schema.yaml`](https://github.com/hotosm/osm-country-exports/blob/main/configs/_hot-schema.yaml).
To change one country, add a file for it.

## Override settings for one country

Create `configs/countries/<ISO3>.yaml`, with the code in capitals. The sweep merges it over
`base.yaml`, so set only the keys that change. Everything else, including the HDX and S3
settings and the layers, still comes from `base.yaml`.

Common reasons, each with a file in the repository to copy from:

=== "Dataset name"

    The country name in HDX titles comes from the ISO3 code. Set `dataset_name` where HDX
    uses a different name. From `NRU.yaml`:

    ```yaml
    # HDX's own name for the location; pycountry still has the former name, Nauru.
    dataset_name: Naoero
    ```

=== "Boundary"

    The export area is the country's ADM0 boundary from geoBoundaries. Some territories have
    none there, so their files carry an inline `boundary.geom`, as `HKG.yaml` does:

    ```yaml
    # Natural Earth 10m admin-0 map units (Hong Kong).
    boundary:
      geom: '{"type":"MultiPolygon","coordinates":[...]}'
    ```

    `boundary.buffer_meters` widens the boundary, for example to include a coastline.

=== "Data source"

    The OpenStreetMap data comes from a Geofabrik country extract clipped to the boundary,
    with the planet file as a fallback. A country Geofabrik cannot look up can read from
    the planet file directly, as `XKX.yaml` does for Kosovo:

    ```yaml
    source:
      osm:
        engine: planet
    ```

A large country can also be given more memory with `parallel.memory_gb`.

[`configs/countries/SDN.yaml.example`](https://github.com/hotosm/osm-country-exports/blob/main/configs/countries/SDN.yaml.example)
shows these keys together. `frequency:` cannot be set here: the schedule supplies it.

To see the merged config a run used, look in `.sweep/merged/<ISO3>.yaml` after a sweep.
Secrets in it stay as `${oc.env:...}` references, so the file is safe to read.

## Change how often a country updates

Edit its entry in
[`scripts/schedule.yaml`](https://github.com/hotosm/osm-country-exports/blob/main/scripts/schedule.yaml),
or move it to another group. See [The schedule](../reference/schedule.md) for the
frequencies. The new frequency reaches HDX the next time the country is published.

## Add a country

Add its ISO3 code to a group in `scripts/schedule.yaml`. Add a
`configs/countries/<ISO3>.yaml` only if it needs one of the overrides above.

## Test a change

Run the country through the sweep without pushing to HDX, then check the files in
`$OEX_DATA_DIR/output/`. The sweep merges `configs/countries/<ISO3>.yaml` over `base.yaml`,
so this tests the override. The files still upload to the S3 bucket, so the public
GeoParquet and downloads change:

```bash
set -a && source .env && set +a && just sweep --group normal --only NPL --no-hdx-push
```

To publish just that country, run the same command without `--no-hdx-push`:

```bash
set -a && source .env && set +a && just sweep --group normal --only NPL
```
