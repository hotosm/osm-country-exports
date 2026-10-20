# osm-country-exports

HOT OpenStreetMap country-scale HDX exports, driven by
[`oex`](https://github.com/osgeonepal/oex). One job, one `oex-cli` invocation.

## Layout

`configs/base.yaml` holds the global defaults (HDX, S3, output) and `configs/_hot-schema.yaml`
the export layers with their HDX metadata. `configs/countries/<ISO3>.yaml` overrides a country
and is merged over the base; `configs/events/` holds standalone event configs. Tasking Manager
configs are generated per run into `configs/tasking_manager/` (and `_sandbox/`) from
`configs/_tm-template.yaml`, and `configs/tm_campaigns.yaml` lists the campaigns whose
project boundaries are published.

`scripts/schedule.yaml` says what runs and when, and `scripts/sweep.py` runs it as `oex-cli`
jobs. `scripts/tm_configs.py` generates the Tasking Manager configs,
`scripts/tm_campaign_boundaries.py` publishes campaign boundaries, and
`scripts/publish_source_geometry.py` publishes the geometry a buffered boundary came from.

## Install

```bash
just setup
cp .env.example .env && $EDITOR .env
```

`oex` is installed from PyPI. To run against a local checkout of the library,
install it over the top and leave `pyproject.toml` alone, so the pinned release stays
what a deployment gets:

```bash
uv pip install -e ../path/to/overture2hdx
export UV_NO_SYNC=1
```

`uv run` re-syncs from the lock file before each command, which would replace the
editable install with the pinned release.

## Run

```bash
set -a && source .env && set +a
just sweep --group priority
just sweep --frequency monthly
just sweep --group heavy --frequency "as needed" --only USA
just sweep --dry-run
```

`--group` and `--frequency` are both optional and combine. Omitting one means all of it.
Jobs run in the order `groups:` declares, one at a time unless `--workers` is above 1, each
with a timeout, and a lock stops one sweep from overlapping the next. Failed jobs are listed
by name at the end.

`--no-hdx-push` skips HDX, but the files still upload to the S3 bucket. The
[documentation](https://hotosm.github.io/osm-country-exports/maintain/operate/) lists every
option.

## Documentation

The [documentation site](https://hotosm.github.io/osm-country-exports/) covers using the
data (HDX, the STAC catalog, QGIS, DuckDB), what the exports contain, the schedule,
editing a country, adding an event, and running the exports. Its source is in `docs/`;
preview it with `just docs`.

## Tasking Manager projects

TM project configs are generated from the API before the sweep runs. `just tm`
regenerates the production configs and sweeps them, `just tm-sandbox` does the same for
sandbox projects, and `just tm-configs --dry-run` reports what would change and writes nothing:

```bash
just tm
just tm-sandbox
just tm-configs --dry-run
```

`scripts/tm_configs.py` reads
`/projects/queries/active/?interval=24` (the API caps the interval at 24 hours,
and `&sandbox=true` selects sandbox projects), and writes one config per project.
Configs are kept until removed by hand, because the API reports only what changed in the
interval.

A project has no country code, so its identity is the project id through
`output.s3.folder`, which puts artifacts at
`TM/hotosm_project_{id}/{category}/{geometry}/hotosm_project_{id}_{category}_{geometry}_{format}.zip`.
With no country, the extract comes from a planet PBF clipped to the project polygon.
Set the PBF with `TM_PBF`. Categories follow each project's mapping types.

`--extract` cuts every project's PBF in a single osmium pass and points each
config at its own small file. osmium streams the whole input once per
invocation, so clipping the planet separately for each project would read it
once per project; one pass with N extracts reads it once in total. The per
project files land in `data/tm/`, or `data/tm_sandbox/`, and `--pbf-dir` moves
them. `--extract` needs a local path, since osmium cannot read `s3://`; without
it, each config points at the whole source PBF instead.

A project whose extract comes out empty is reported, because that means the
source PBF does not cover it and the export would publish nothing.

## Publishing alongside an export

Two resources belong on a dataset that `oex` does not produce, so each has its own
script and `just` recipe.

`just tm-boundaries` publishes the project boundaries of a Tasking Manager campaign
as one GeoJSON, so a dataset shows where mapping was organised and how far each task
got. Campaigns are listed in `configs/tm_campaigns.yaml`, keyed by their exact name
in the Tasking Manager. Add `--dry-run` to see what
would be published.

`just source-geometry CONFIG NAME` publishes the geometry a boundary was derived
from. `oex` publishes the extraction boundary as the Area of Interest resource, so
this matters only when `boundary.buffer_meters` widens it, and the config is refused
without a buffer. The uploaded filename becomes the resource's public URL, so pass
`--file-name` to keep an existing resource at the address people already have.

## Bumping the HOT schema

`configs/_hot-schema.yaml` holds the layer list and the HDX metadata prose for the
country exports. oex ships a similar example at `configs/examples/hot-schema.yaml`.
Reconcile the two by hand when the upstream example changes.
