# osm-country-exports

HOT OpenStreetMap country-scale HDX exports, driven by
[`oex`](https://github.com/osgeonepal/oex). One job, one `oex-cli` invocation.

## Layout

```
configs/
  base.yaml                 global defaults: HDX, S3, output dir
  _hot-schema.yaml          vendored copy of oex's hot-schema.yaml (OSM-only)
  _tm-template.yaml         template for Tasking Manager project exports
  countries/<ISO3>.yaml     optional per-country override, merged over base.yaml
  events/<name>.yaml        standalone configs for event responses
  tasking_manager/          generated per run, one config per active TM project
  tasking_manager_sandbox/  the same for TM sandbox projects
scripts/
  schedule.yaml             what runs, and when
  sweep.py                  resolves the schedule into oex-cli jobs and runs them
  tm_configs.py             generates the Tasking Manager configs
systemd/                    daily, weekly and monthly timers
```

## Install

```bash
just setup
cp .env.example .env && $EDITOR .env
```

## Run

```bash
just one NPL                                          # single country, no HDX push
source .env && just sweep --group priority            # one group
source .env && just sweep --frequency monthly         # one frequency
source .env && just sweep --group heavy --frequency monthly
source .env && just sweep                             # everything enabled
just sweep --dry-run                                  # print the commands, run nothing
just sweep --json                                     # print the job list, run nothing
just sweep --group priority --no-hdx-push             # real exports, nothing published
```

Both filters are optional and combine. Omitting one means all of it. Jobs run one
at a time in the order `groups:` declares, each with a timeout, and a lock stops
one sweep from overlapping the next. Failed jobs are listed by name at the end.

For systemd, see [`systemd/README.md`](systemd/README.md).

## The schedule

`scripts/schedule.yaml` is the single answer to what runs and when. `groups:`
declares the run order, and position in that list is priority. Every group holds
one of two job sources:

- `countries:` a map of ISO3 to frequency. The config is
  `configs/countries/<ISO3>.yaml` merged over `configs/base.yaml`, or
  `configs/base.yaml` alone.
- `dir:` a folder of standalone configs, one job per file. Frequency comes from
  each config's own `frequency:` field, falling back to the group's.

Any value is either a bare frequency or a mapping:

```yaml
AFG: monthly
YEM: {frequency: monthly, enabled: false}
SDN: {frequency: monthly, expires: 2026-12-31}
```

`frequency: as needed` never runs on a schedule. Run those by hand with
`just sweep --frequency "as needed"`. Disabled and expired jobs are skipped with
the reason printed, never silently.

Which `oex-cli` subcommand a job uses comes from `source.osm.enabled` and
`source.overture.enabled` in its config, so it is never declared twice. A config
enabling both becomes two jobs.

## Adding a country

Add it to a group in `scripts/schedule.yaml`. Order inside a group is preserved.

## Per-country overrides

Drop `configs/countries/<ISO3>.yaml` to override `base.yaml` for that country.
Only the keys you set are replaced, everything else comes from `base.yaml`. See
[`configs/countries/SDN.yaml.example`](configs/countries/SDN.yaml.example).

## Adding an event, or another folder of configs

Put a standalone config in `configs/events/` and it joins the `events` group on
the next run. Set its `frequency:` to schedule it, or leave it `as needed` to keep
it manual. Use the group's `overrides:` block to disable one file or give it an
expiry date without editing the config.

Another folder needs no code change, only a group in `scripts/schedule.yaml` and
its name in `groups:`:

```yaml
tasking_manager:
  enabled: true
  dir: configs/tasking_manager
  frequency: daily
```

## Tasking Manager projects

TM projects come from the API rather than from files, so their configs are
generated before the sweep runs:

```bash
just tm                   # regenerate production configs, then sweep them
just tm-sandbox           # the same for sandbox projects
just tm-configs --dry-run # see what would change, write nothing
```

`scripts/tm_configs.py` reads
`/projects/queries/active/?interval=24` (the API caps the interval at 24 hours,
and `&sandbox=true` selects sandbox projects), writes one config per project,
and removes configs for projects that are no longer active.

A project has no country code, so its identity is the project id through
`output.s3.folder`, which puts artifacts at
`TM/{project_id}/hotosm_project_{project_id}_{category}_{format}.zip`. Because
there is no country, the extract comes from a planet PBF clipped to the project
polygon rather than from a Geofabrik country extract. Set the PBF with
`TM_PBF`, and `TM_SANDBOX_PBF` for sandbox projects. Categories follow each
project's mapping types.

`--extract` cuts every project's PBF in a single osmium pass and points each
config at its own small file. osmium streams the whole input once per
invocation, so clipping the planet separately for each project would read it
once per project; one pass with N extracts reads it once in total. The per
project files land in `data/tm/`, or `data/tm_sandbox/`, and `--pbf-dir` moves
them. `--extract` needs a local path, since osmium cannot read `s3://`; without
it, each config points at the whole source PBF instead.

A project whose extract comes out empty is reported, because that means the
source PBF does not cover it and the export would publish nothing.

## Bumping the HOT schema

`configs/_hot-schema.yaml` is vendored from oex's
`configs/examples/hot-schema.yaml`. Replace the file and commit the diff.

## Docs

- [`docs/managing-hdx.md`](docs/managing-hdx.md)
