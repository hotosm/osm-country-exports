# Per-country overrides

Drop a file at `<ISO3>.yaml` (uppercase) to override `configs/base.yaml` for
that country. The sweep merges it over `base.yaml` and passes the result to
`oex-cli`, so only the keys you set are replaced and everything else, including
HDX and S3 settings and the HOT category list, still applies.

See [`SDN.yaml.example`](SDN.yaml.example) for `dataset_name`, inline
`boundary.geom`, and switching `source.osm.engine` to `planet`.

The sweep picks the override automatically when it processes that ISO3. The
merged file is written to `.sweep/merged/<ISO3>.yaml`, which is gitignored and
useful when you want to see exactly what ran. Interpolations such as
`${oc.env:HDX_API_KEY}` are left unresolved, so no secret is written to it.

The CLI `--iso3` flag still wins over any `iso3:` set inside the file.
