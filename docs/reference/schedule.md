# Schedule groups and frequencies

[`scripts/schedule.yaml`](https://github.com/hotosm/osm-country-exports/blob/main/scripts/schedule.yaml)
says what is exported and how often. It is split into groups, run in the order the
`groups:` list declares, and each group sets one update frequency for everything in it.

| Group | Holds | Update frequency |
| --- | --- | --- |
| `priority` | The 22 HDX Data Grid locations, run first | Monthly |
| `normal` | 109 countries and territories | Monthly |
| `high_income` | 95 high-income countries and territories | Quarterly |
| `big` | 12 large countries, such as the USA, Brazil, India and Russia | Yearly |
| `minimal` | 12 uninhabited or nearly empty territories, such as Antarctica | As needed, run by hand |
| `events` | Disaster and response exports, one config file each, in `configs/events/` | Set per config |
| `tasking_manager` | One export per active Tasking Manager project | Daily |
| `tasking_manager_sandbox` | The same for the Tasking Manager sandbox | Daily |

## Group settings

A group holds one of two job sources.

- `countries:` lists ISO3 codes. Each country's config is `configs/base.yaml`, with
  `configs/countries/<ISO3>.yaml` merged over it when that file exists.
- `dir:` names a folder of standalone configs, one job per file. A config's own
  `frequency:` wins over the group's.

`frequency:` is the group's update frequency. `workers:` sets how many countries export
at once in a country group (1 when left out); each gets an equal share of the memory.

```yaml
normal:
  frequency: monthly
  workers: 2
  countries: [AGO, ALB, ARM]
```

To change a whole group's frequency, edit its `frequency:`. To make one country differ,
write the countries as a mapping. A value there can also disable a job or give it an end
date:

```yaml
countries:
  PAK: weekly
  NPL: null
  YEM: {enabled: false}
  SDN: {expires: 2026-12-31}
```

`null` keeps the group's frequency. Disabled and expired jobs are skipped, and the sweep
prints why.

## Frequencies

The frequencies are the ones HDX uses: `daily`, `weekly`, `monthly`, `quarterly`,
`yearly`, and `as needed`. `just sweep --due` runs every job whose last publish is older
than its frequency, group by group in order. The last publish is the oldest `updated` time
on the job's STAC Items, which oex sets when a layer reaches HDX. A layer with no Item,
such as a new category, or with an undated one, left by a failed publish, makes its job due.
A job that doesn't publish to HDX, such as a Tasking Manager project, is always due. Source
`.env` first, since the sweep reads every config. `just daily` runs it after refreshing the
Tasking Manager configs. Jobs on `as needed` run only by hand, with
`--frequency "as needed"`.

For a country, the frequency is also the update frequency its HDX datasets show, and the
schedule is the only place to set it. A change reaches HDX the next time the country is
published; `scripts/sync_hdx_frequency.py --apply` updates HDX straight away. For a config
in a `dir:` group, HDX shows the config's own `frequency:`, and a frequency in the group's
`overrides:` only decides when it runs. A missed run shows as outdated on the
[update status page](https://hotosm.github.io/hot2hdx-status/).
