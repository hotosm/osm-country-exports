# systemd install

Both units assume the repo lives at `/opt/osm-country-exports` and runs as
user `oex`. Edit `WorkingDirectory=`, `EnvironmentFile=`, and `User=`/`Group=`
in the service file if you deploy elsewhere.

## Install

```bash
sudo cp systemd/osm-country-exports.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now osm-country-exports.timer
```

## Inspect

```bash
systemctl list-timers osm-country-exports.timer
systemctl status osm-country-exports.service
journalctl -f -u osm-country-exports.service
```

## Run ad-hoc

```bash
sudo systemctl start osm-country-exports.service
```

## Host setup

```bash
sudo useradd -m -s /bin/bash oex
sudo chown -R oex:oex /opt/osm-country-exports
sudo -u oex bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo ln -s /home/oex/.local/bin/uv /usr/local/bin/uv
```

If the host uses AWS SSO, `aws sso login --profile admin` as the `oex` user
before the next timer tick so `~oex/.aws/sso/cache` is warm.
