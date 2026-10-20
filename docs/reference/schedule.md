# The schedule

[`scripts/schedule.yaml`](https://github.com/hotosm/osm-country-exports/blob/main/scripts/schedule.yaml)
says what is exported and how often. It is split into groups, run in the order the
`groups:` list declares.

| Group | Holds | Update frequency |
| --- | --- | --- |
| `priority` | 27 countries, run first | Monthly |
| `normal` | 191 countries and territories | Monthly |
| `heavy` | 32 large countries, such as the USA, Brazil, India and Russia | As needed, run by hand |
| `events` | Disaster and response exports, one config file each, in `configs/events/` | Set per config |
| `tasking_manager` | One export per active Tasking Manager project | Daily |
| `tasking_manager_sandbox` | The same for the Tasking Manager sandbox | Daily |

## How a group lists its jobs

A group holds one of two job sources.

- `countries:` maps ISO3 codes to a frequency. Each country's config is
  `configs/base.yaml`, with `configs/countries/<ISO3>.yaml` merged over it when that file
  exists.
- `dir:` names a folder of standalone configs, one job per file. A job's frequency comes
  from the config's own `frequency:`, or from the group's `frequency:` when the config has
  none.

A value is either a frequency or a mapping that can also disable a job or give it an end
date:

```yaml
AFG: monthly
YEM: {frequency: monthly, enabled: false}
SDN: {frequency: monthly, expires: 2026-12-31}
```

Disabled and expired jobs are skipped, and the sweep prints why.

## Frequencies

A job's frequency decides which sweep runs it: `just sweep --frequency monthly` runs the
monthly jobs, and so on for `daily` and `weekly`. Run each on its cycle, for example the
monthly sweep at the start of each month. Jobs on `as needed` run only with
`--frequency "as needed"`.

For a country, the frequency is also the update frequency its HDX datasets show, and the
schedule is the only place to set it. For a config in a `dir:` group, HDX shows the
config's own `frequency:`, and a frequency in the group's `overrides:` only picks the sweep. A missed run shows as outdated on
the [update status page](https://hotosm.github.io/hot2hdx-status/).
