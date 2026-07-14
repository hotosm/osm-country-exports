# osm-country-exports

HOT OpenStreetMap country-scale HDX exports, driven by
[`oex`](https://github.com/osgeonepal/oex). One country, one `oex-cli osm`
invocation.

## Layout

```
configs/
  base.yaml                 global defaults: HDX, S3, output dir
  _hot-schema.yaml          vendored copy of oex's hot-schema.yaml (OSM-only)
  countries/<ISO3>.yaml     optional per-country override
scripts/
  countries.yaml            priority / normal / big groups (248 ISO3s)
  list_countries.py         prints ISO3s for a group
  sweep.sh                  iterates and runs oex-cli per country
systemd/                    monthly timer
```

## Install

```bash
just setup
cp .env.example .env && $EDITOR .env
```

## Run

```bash
just one NPL              # single country, no HDX push
source .env && just sweep priority    # one group
source .env && just sweep             # everything
```

For systemd, see [`systemd/README.md`](systemd/README.md).

## Per-country overrides

Drop `configs/countries/<ISO3>.yaml` to override `base.yaml` for that country.
OmegaConf merges; only the keys you set are replaced. See
[`configs/countries/SDN.yaml.example`](configs/countries/SDN.yaml.example).

## Adding a country

Edit `scripts/countries.yaml`. The `priority` block runs first, then `normal`,
then `big`; order inside each block is preserved.

## Bumping the HOT schema

`configs/_hot-schema.yaml` is vendored from oex's
`configs/examples/hot-schema.yaml`. Replace the file and commit the diff.

## Docs

- [`docs/managing-hdx.md`](docs/managing-hdx.md)
