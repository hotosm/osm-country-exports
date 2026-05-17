# Per-country overrides

Drop a file at `<ISO3>.yaml` (uppercase) to override `configs/base.yaml` for
that country. OmegaConf merges only the keys you set.

See [`SDN.yaml.example`](SDN.yaml.example) for `dataset_name`, inline
`boundary.geom`, and switching `source.osm.engine` to `planet`.

The sweep picks the override automatically when it processes that ISO3; the CLI
`--iso3` flag still wins over any `iso3:` set inside the file.
