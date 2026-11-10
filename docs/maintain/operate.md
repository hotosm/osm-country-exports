# Run and operate

## Set up

```bash
just setup
cp .env.example .env
```

Fill in `.env` with the S3 bucket, the HDX key, organisation and maintainer, and `TM_PBF`
(the planet file, for Tasking Manager exports). Point `OEX_DATA_DIR` at a large disk; the
planet file alone was about 95 GB in October 2026.

## Run exports

```bash
set -a && source .env && set +a
just sweep --due
just sweep --due --dry-run
just sweep --group big --only USA
just sweep --group normal --workers 4
```

`--due` runs whatever is due, as described in
[Schedule groups and frequencies](../reference/schedule.md). Run `just daily` once a day,
for example from a systemd timer: it refreshes the Tasking Manager configs, then runs
`just sweep --due`. Run `just sweep --help` for every option. A sweep resumes by default, skipping layers
already uploaded from the same snapshot. A layer whose features and settings match its last
publish is not rebuilt either; only its HDX date moves forward. `--no-hdx-push` skips HDX, but files still upload
to S3.

## Tasking Manager projects

```bash
just tm
just tm-sandbox
```

Each writes a config for every project active in the last 24 hours, cuts its area from
`TM_PBF`, then runs every config in the group's folder. Configs stay until removed by hand.

## Change the layers

Edit
[`configs/_hot-schema.yaml`](https://github.com/hotosm/osm-country-exports/blob/main/configs/_hot-schema.yaml).
A change applies to every country on its next run.

## Check the results

- The [update status page](https://hotosm.github.io/hot2hdx-status/) shows overdue datasets.
- `.sweep/merged/<ISO3>.yaml` shows the exact config a country ran with.
