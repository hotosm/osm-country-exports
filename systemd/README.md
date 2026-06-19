# systemd install

Templated service + three timers (daily/weekly/monthly). Each timer fires
only the countries tagged for its cadence in `scripts/countries.yaml`. Order
within a tick is always priority -> normal -> big. To move a country between
cadences, change its one-word cadence tag. To skip a whole group, flip its
`enabled` flag.

## Prerequisites

Runs as `oex` from `/opt/osm-country-exports`. Edit the unit if elsewhere.

```bash
sudo useradd -m -U -s /bin/bash oex
sudo git clone https://github.com/hotosm/osm-country-exports.git /opt/osm-country-exports
sudo chown -R oex:oex /opt/osm-country-exports

sudo -u oex bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo ln -s /home/oex/.local/bin/uv /usr/local/bin/uv

sudo -u oex bash -c 'cd /opt/osm-country-exports && uv sync'
```

Data dir (planet PBF is ~80GB, do NOT leave on root). Point `OEX_DATA_DIR`
at a large volume; `output/`, OSM cache, planet PBF, and pcodes cache all
land underneath it.

```bash
sudo mkdir -p /mnt/disk/oex
sudo chown oex:oex /mnt/disk/oex
```

Place your `.env` at `/opt/osm-country-exports/.env`, owned by `oex`, mode 600:

```dotenv
OEX_DATA_DIR=/mnt/disk/oex
OEX_S3_BUCKET=...
HDX_API_KEY=...
HDX_OWNER_ORG=...
HDX_MAINTAINER=...
```

AWS SSO host: `sudo -u oex aws sso login --profile admin` before first tick.

Sanity check: `sudo -u oex bash -c 'cd /opt/osm-country-exports && uv run oex-cli --help'`

## Install

```bash
sudo cp systemd/osm-country-exports@.service /etc/systemd/system/
sudo cp systemd/osm-country-exports@{daily,weekly,monthly}.timer /etc/systemd/system/
sudo cp systemd/osm-country-exports.tmpfiles.conf /etc/tmpfiles.d/
sudo systemd-tmpfiles --create /etc/tmpfiles.d/osm-country-exports.tmpfiles.conf
sudo systemctl daemon-reload
sudo systemctl enable --now osm-country-exports@{daily,weekly,monthly}.timer
```

`systemd-tmpfiles-clean.timer` (enabled by default) sweeps the data dirs
daily and deletes anything older than 30 days. Edit
`osm-country-exports.tmpfiles.conf` to change the retention or paths.

## Inspect

```bash
systemctl list-timers 'osm-country-exports@*'                                 # next fire times
journalctl -fu 'osm-country-exports@*'                              #logs
journalctl -f -u osm-country-exports@monthly.service
systemctl status osm-country-exports@monthly.service                            
```

## Ad-hoc

```bash
sudo systemctl start osm-country-exports@daily.service     # cadence or group via systemd
sudo -u oex bash -c 'cd /opt/osm-country-exports && uv run oex-cli osm --config configs/base.yaml --iso3 NPL'   # one country
```

## Maintain

Update repo and deps:

```bash
sudo -u oex bash -c 'cd /opt/osm-country-exports && git pull && uv sync'
```

Unit-file changes (anything under `systemd/`): re-cp, then

```bash
sudo systemctl daemon-reload
sudo systemctl restart osm-country-exports@{daily,weekly,monthly}.timer
```

Toggle a group without touching systemd: flip `<group>.enabled` in
`scripts/countries.yaml`. The script re-reads on every tick; a disabled
group is silently skipped (stderr line per disabled group).

Stop everything:

```bash
sudo systemctl disable --now osm-country-exports@{daily,weekly,monthly}.timer
```
