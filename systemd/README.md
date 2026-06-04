# systemd install

Units assume the repo lives at `/opt/osm-country-exports` and runs as user
`oex`. Edit `WorkingDirectory=`, `EnvironmentFile=`, and `User=`/`Group=` in
`osm-country-exports@.service` if you deploy elsewhere.

One templated service takes the sweep group as its instance (`%i`). Three
timer files schedule the daily / weekly / monthly cadences. The cadence
on/off switch lives in `scripts/countries.yaml` (`schedule.<name>.enabled`)
so timers can stay permanently enabled; flipping `enabled: false` makes the
tick a clean no-op (skip log, exit 0).

Default fire times (staggered to avoid Sun-1st-of-month collisions):

| timer    | OnCalendar              |
|----------|-------------------------|
| daily    | `*-*-* 02:00:00`        |
| weekly   | `Mon *-*-* 03:00:00`    |
| monthly  | `*-*-01 04:00:00`       |

## Install

```bash
sudo cp systemd/osm-country-exports@.service /etc/systemd/system/
sudo cp systemd/osm-country-exports@{daily,weekly,monthly}.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now osm-country-exports@daily.timer \
                            osm-country-exports@weekly.timer \
                            osm-country-exports@monthly.timer
```

## Inspect

```bash
systemctl list-timers 'osm-country-exports@*'
systemctl status osm-country-exports@daily.service
journalctl -fu 'osm-country-exports@*'
```

## Run ad-hoc

```bash
sudo systemctl start osm-country-exports@daily.service       # one cadence
sudo systemctl start osm-country-exports@priority.service    # one ordering group
sudo systemctl start osm-country-exports@all.service         # full sweep
```

`%i` is passed straight to `sweep.sh`, so any group name `list_countries.py`
understands works as an instance.

## Host setup

```bash
sudo useradd -m -s /bin/bash oex
sudo chown -R oex:oex /opt/osm-country-exports
sudo -u oex bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo ln -s /home/oex/.local/bin/uv /usr/local/bin/uv
```

If the host uses AWS SSO, `aws sso login --profile admin` as the `oex` user
before the next timer tick so `~oex/.aws/sso/cache` is warm.
