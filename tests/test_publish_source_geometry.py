import json

import publish_source_geometry as psg

SQUARE = json.dumps({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]})

CONFIG = """
iso3: NPL
key: t
hdx:
  combine: true
  combined:
    name: hot_test_npl
boundary:
  geom: '{geom}'
  buffer_meters: {buffer}
categories:
  - name: buildings
    osm:
      enabled: true
      filter:
        building: true
"""


def write_config(tmp_path, buffer):
    path = tmp_path / "c.yaml"
    path.write_text(CONFIG.format(geom=SQUARE, buffer=buffer), encoding="utf-8")
    return path


def run(monkeypatch, path, extra=()):
    monkeypatch.setattr(
        "sys.argv", ["publish_source_geometry.py", "--config", str(path), "--name", "n", *extra]
    )
    return psg.main()


def test_a_config_without_a_buffer_is_refused(tmp_path, monkeypatch):
    """Without a buffer this geometry is the AOI, which oex already publishes."""
    assert run(monkeypatch, write_config(tmp_path, 0), ["--dry-run"]) == 2


def test_a_dry_run_publishes_nothing(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("a dry run must not upload")

    monkeypatch.setattr(psg, "attach_geojson", fail)
    monkeypatch.setattr(psg, "configure", fail)
    assert run(monkeypatch, write_config(tmp_path, 200), ["--dry-run"]) == 0
