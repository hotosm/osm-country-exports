# Add an event

An event export covers one area, such as a flood or an earthquake zone. Each event is a
standalone config in
[`configs/events/`](https://github.com/hotosm/osm-country-exports/tree/main/configs/events);
it does not merge over `base.yaml`. Use
[`NPL-FL-2026-flood-extent.yaml`](https://github.com/hotosm/osm-country-exports/blob/main/configs/events/NPL-FL-2026-flood-extent.yaml)
as the worked example.

## 1. Copy an existing event

Copy the closest example and name it `<ISO3>-<hazard>-<year>-<name>.yaml`.

## 2. Change these fields in the copy

```yaml
iso3: NPL
key: hot_flood
frequency: as needed

boundary:
  geom: '{"type":"Polygon","coordinates":[...]}'
  buffer_meters: 200

output:
  s3:
    folder: NPL_FLOOD
  stac:
    group: activations

hdx:
  time_period_start: "2026-08-26"
  combine: true
  combined:
    name: hot_flood_npl
    title: Nepal Flood 2026 Flood Affected Area, Bhote Koshi and Trishuli

categories_file: configs/events/_npl-flood-categories.yaml
```

- `key` starts the HDX dataset names; give each event its own.
- `boundary.geom` is the area as GeoJSON; `buffer_meters` widens it.
- `output.s3.folder` keeps the files apart from the country export.
- `output.stac.group` lists the event under its own catalog.
- `hdx.time_period_start` is the date of the first upload.
- `hdx.combine` publishes all layers as one dataset, `hdx.combined.name`.
- `categories_file` lists the layers. Files starting with `_` are shared and never run alone.

## 3. Run it

```bash
set -a && source .env && set +a
uv run oex-cli osm --config configs/events/NPL-FL-2026-flood-extent.yaml --no-hdx-push
uv run oex-cli osm --config configs/events/NPL-FL-2026-flood-extent.yaml --hdx-push
```

The first run checks the output without pushing to HDX (files still upload to S3); the
second publishes. With Overture enabled, run `oex-cli overture` with the same config too.

## 4. Keep it updating

Set `frequency:` to `daily`, `weekly` or `monthly`; this is also what HDX shows. The
`events` group's `overrides:` in `scripts/schedule.yaml` can change when a file runs,
disable it, or set an `expires:` date, without changing what HDX shows.

When the event ends, set `frequency:` back to `as needed` and run it once so HDX shows
"As needed".
