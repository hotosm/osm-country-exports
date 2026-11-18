# Country exports on Windmill

Monthly (and weekly/daily) OSM exports for ~40 countries, run as high-memory
batch jobs on [Windmill](https://www.windmill.dev/).

## The idea

```
3 schedules ──▶ dispatcher flow          (light worker)
 daily            reads scripts/countries.yaml
 weekly           runs main.py once per country, ~2 at a time
 monthly          ├──▶ main.py  iso3=AFG   [heavy]
                  ├──▶ main.py  iso3=SDN   [heavy]
                  └──▶ main.py  iso3=...   [heavy]
```

Every country runs the **same script** (`main.py`) with **different arguments**.
The arguments come from `scripts/countries.yaml`, which stays the source of
truth - adding a country is still a one-line edit there.

- **`main.py`** - the export itself. One country per run. Tagged `heavy` so it
  only lands on the high-memory worker pool.
- **Dispatcher flow** - a thin coordinator on a normal worker. Reads
  `countries.yaml` and launches one `heavy` job per country.
- **Schedules** - three of them (daily/weekly/monthly), each just runs the
  dispatcher with a different `cadence` argument. Replaces the three GitHub
  Actions.

The worker pool, the `heavy` tag, KEDA autoscaling and Karpenter spot instances
are all set up in [hotosm/k8s-infra](https://github.com/hotosm/k8s-infra). This
repo only holds the script, the flow and the schedules.

## How scaling works

1. The dispatcher queues one `heavy` job per country.
2. The `heavy` worker pool listens on that queue; KEDA sees the jobs and scales
   it up from zero.
3. No room in the cluster? Karpenter spins up a spot instance.
4. Workers chew through ~2 at a time, then the pool scales back to zero once the
   queue is empty.

Only `main.py` is `heavy`. The dispatcher is light, so coordinating the run
never ties up a high-memory slot.

## The script

`main.py` is one country, one run - the same as `just one <ISO3>` today.
Windmill builds the run form from the function arguments automatically.

```python
def main(
    iso3: str,
    priority: int = 50,        # queue priority (1-100), set by the dispatcher
    cadence: str = "monthly",  # which schedule fired this
    hdx_push: bool = True,
    config_path: str = "",     # blank = auto: countries/<ISO3>.yaml, else base.yaml
):
    ...
```

Config lookup is the same rule as `sweep.sh`: use `configs/countries/<ISO3>.yaml`
if it exists, otherwise `configs/base.yaml`.

## How the 3 params map

- **country code** - the `iso3` argument, one per loop item.
- **frequency** - the `cadence:` value in `countries.yaml` decides which of the
  three schedules picks the country up.
- **priority** - the group (`priority`/`normal`/`big`). The dispatcher runs the
  priority group first and gives those jobs a higher Windmill priority number,
  so they jump the queue when `heavy` slots are tight.

## The dispatcher flow

Two steps:

1. **List** (light) - reads `countries.yaml` for the fired cadence and returns
   `[{iso3, config, priority}, ...]`, ordered priority → normal → big. Basically
   `list_countries.py` returning structured rows.
2. **For-loop** over that list, running `main.py` per country:
   - **Parallel, parallelism = 2** - the "a couple at a time" knob. Bump it once
     the pool scales comfortably.
   - **Continue on error** - one failed country doesn't kill the run; it just
     shows up as a failed iteration.
   - The loop step is tagged `heavy`; the flow itself is not.

## Deploying (git sync)

The script, flow and schedules live in this repo and sync to Windmill - that's
how "Windmill points to the remote script".

- Use `wmill` git sync with `includeSchedules: true` in `wmill.yaml` (schedules
  are off by default).
- Run it from a GitHub Action on push to `main`, so merging a PR deploys
  everything with no clicking in the UI.

## Running it

- **Full run** - happens automatically on schedule. To kick one off now, open
  the dispatcher flow and run it with the cadence you want.
- **One country** - run `main.py` from its form with a single `iso3`. No flow
  needed. Same as `just one <ISO3>`.
- **Restart failed countries** - two options, both safe:
  1. Open the failed country's job and hit **Re-run**. Isolated - won't touch
     other countries. (Best for one-offs.)
  2. On the flow run, pick the failed step and **Restart from here**. Windmill
     skips the countries that already succeeded.

  Re-running is safe either way: completed countries are skipped,
  `output.resume: true` resumes a partial export, and HDX/S3 writes overwrite in
  place.
