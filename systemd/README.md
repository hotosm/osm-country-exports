# systemd install

Templated service + three timers (daily/weekly/monthly), each runs `sweep.sh %i`.
Cadence on/off lives in `scripts/countries.yaml` (`schedule.<name>.enabled`); a
disabled tick is a no-op.

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

Place your `.env` (HDX token, S3 keys, ...) at `/opt/osm-country-exports/.env`,
owned by `oex`, mode 600. AWS SSO host: `sudo -u oex aws sso login --profile admin`
before first tick.

Sanity check: `sudo -u oex bash -c 'cd /opt/osm-country-exports && uv run oex-cli --help'`

## Install

```bash
sudo cp systemd/osm-country-exports@.service /etc/systemd/system/
sudo cp systemd/osm-country-exports@{daily,weekly,monthly}.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now osm-country-exports@{daily,weekly,monthly}.timer
```

## Inspect

```bash
systemctl list-timers 'osm-country-exports@*'                                 # next fire times
journalctl -fu 'osm-country-exports@*'                              #logs
journalctl -f -u osm-country-exports@monthly.service
systemctl status osm-country-exports@monthly.service                            
```

## Ad-hoc

```bash
sudo systemctl start osm-country-exports@daily.service     # any group sweep.sh accepts (daily/weekly/monthly/priority/normal/big/all)
```

Or bypass systemd entirely:

```bash
sudo -u oex bash -c 'cd /opt/osm-country-exports && scripts/sweep.sh daily'
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

Toggle a cadence without touching systemd: flip `schedule.<name>.enabled` in
`scripts/countries.yaml`. The script re-reads on every tick; a disabled tick
logs a skip line and exits 0.

Stop everything:

```bash
sudo systemctl disable --now osm-country-exports@{daily,weekly,monthly}.timer
```
