from datetime import date

import pytest
import sweep
import yaml
from oex.config.loader import load_config

TODAY = date(2026, 8, 5)

OSM_CONFIG = "iso3: NPL\nsource:\n  osm:\n    enabled: true\n  overture:\n    enabled: false\n"
OVERTURE_CONFIG = "iso3: NPL\nsource:\n  osm:\n    enabled: false\n  overture:\n    enabled: true\n"
BOTH_CONFIG = "iso3: NPL\nsource:\n  osm:\n    enabled: true\n  overture:\n    enabled: true\n"


def write_config(folder, name, body, frequency=None):
    text = f"frequency: {frequency}\n{body}" if frequency else body
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def resolve(schedule, group=None, frequency=None):
    return sweep.resolve(schedule, group, frequency, TODAY)


def countries_schedule(countries, enabled=True):
    return {
        "groups": ["priority"],
        "priority": {"enabled": enabled, "countries": countries},
    }


def test_bare_value_is_a_frequency():
    assert sweep.attributes("daily", None) == {"frequency": "daily", "enabled": True}


def test_mapping_value_overrides_the_group_default():
    attrs = sweep.attributes({"frequency": "weekly", "enabled": False}, "monthly")
    assert attrs == {"frequency": "weekly", "enabled": False}


def test_missing_value_falls_back_to_the_group_default():
    assert sweep.attributes(None, "monthly")["frequency"] == "monthly"


def test_a_value_that_is_neither_is_rejected():
    with pytest.raises(sweep.ScheduleError):
        sweep.attributes(7, None)


def test_frequency_filter_selects_matching_jobs_only():
    jobs, _ = resolve(countries_schedule({"NPL": "daily", "SDN": "monthly"}), frequency="daily")
    assert [job.iso3 for job in jobs] == ["NPL"]


def test_frequency_mismatch_is_silent():
    _, skipped = resolve(countries_schedule({"SDN": "monthly"}), frequency="daily")
    assert skipped == []


def test_disabled_job_is_skipped_with_a_reason():
    jobs, skipped = resolve(countries_schedule({"NPL": {"frequency": "daily", "enabled": False}}))
    assert jobs == []
    assert skipped == ["priority/NPL: disabled"]


def test_disabled_group_is_skipped_with_a_reason():
    jobs, skipped = resolve(countries_schedule({"NPL": "daily"}, enabled=False))
    assert jobs == []
    assert skipped == ["priority: group disabled"]


def test_expired_job_is_skipped():
    entry = {"frequency": "daily", "expires": date(2026, 8, 4)}
    jobs, skipped = resolve(countries_schedule({"NPL": entry}))
    assert jobs == []
    assert skipped == ["priority/NPL: expired 2026-08-04"]


def test_expiry_is_inclusive_of_the_final_day():
    entry = {"frequency": "daily", "expires": TODAY}
    jobs, _ = resolve(countries_schedule({"NPL": entry}))
    assert len(jobs) == 1


def test_manual_jobs_stay_out_of_an_unfiltered_sweep():
    jobs, skipped = resolve(countries_schedule({"NPL": sweep.MANUAL_FREQUENCY}))
    assert jobs == []
    assert "manual" in skipped[0]


def test_manual_jobs_run_when_asked_for_by_name():
    schedule = countries_schedule({"NPL": sweep.MANUAL_FREQUENCY})
    jobs, _ = resolve(schedule, frequency=sweep.MANUAL_FREQUENCY)
    assert [job.iso3 for job in jobs] == ["NPL"]


def test_a_job_without_a_frequency_anywhere_is_an_error():
    with pytest.raises(sweep.ScheduleError):
        resolve(countries_schedule({"NPL": {"enabled": True}}))


def test_unknown_group_filter_is_an_error():
    with pytest.raises(sweep.ScheduleError):
        resolve(countries_schedule({"NPL": "daily"}), group="nope")


def test_group_listed_without_a_block_is_an_error():
    with pytest.raises(sweep.ScheduleError):
        resolve({"groups": ["priority", "ghost"], "priority": {"countries": {"NPL": "daily"}}})


def test_group_with_neither_countries_nor_dir_is_an_error():
    with pytest.raises(sweep.ScheduleError):
        resolve({"groups": ["priority"], "priority": {"enabled": True}})


def test_groups_run_in_declared_order():
    schedule = {
        "groups": ["second", "first"],
        "first": {"countries": {"AAA": "daily"}},
        "second": {"countries": {"BBB": "daily"}},
    }
    jobs, _ = resolve(schedule)
    assert [job.iso3 for job in jobs] == ["BBB", "AAA"]


@pytest.fixture
def events_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "REPO_ROOT", tmp_path)
    folder = tmp_path / "configs" / "events"
    folder.mkdir(parents=True)
    return folder


def test_folder_job_uses_the_frequency_declared_in_its_own_config(events_dir):
    write_config(events_dir, "quake.yaml", OSM_CONFIG, frequency="daily")
    schedule = {"groups": ["events"], "events": {"dir": "configs/events", "frequency": "monthly"}}
    jobs, _ = resolve(schedule, frequency="daily")
    assert [job.id for job in jobs] == ["events/quake"]


def test_folder_job_falls_back_to_the_group_frequency(events_dir):
    write_config(events_dir, "quake.yaml", OSM_CONFIG)
    schedule = {"groups": ["events"], "events": {"dir": "configs/events", "frequency": "monthly"}}
    jobs, _ = resolve(schedule, frequency="monthly")
    assert [job.id for job in jobs] == ["events/quake"]


def test_a_per_file_override_beats_the_config_and_the_group(events_dir):
    write_config(events_dir, "quake.yaml", OSM_CONFIG, frequency="daily")
    schedule = {
        "groups": ["events"],
        "events": {
            "dir": "configs/events",
            "frequency": "monthly",
            "overrides": {"quake.yaml": "weekly"},
        },
    }
    jobs, _ = resolve(schedule, frequency="weekly")
    assert [job.id for job in jobs] == ["events/quake"]


def test_a_per_file_override_can_disable_one_file(events_dir):
    write_config(events_dir, "quake.yaml", OSM_CONFIG, frequency="daily")
    schedule = {
        "groups": ["events"],
        "events": {"dir": "configs/events", "overrides": {"quake.yaml": {"enabled": False}}},
    }
    jobs, skipped = resolve(schedule, frequency="daily")
    assert jobs == []
    assert skipped == ["events/quake: disabled"]


def test_missing_folder_is_an_error(events_dir):
    schedule = {"groups": ["events"], "events": {"dir": "configs/nowhere", "frequency": "daily"}}
    with pytest.raises(sweep.ScheduleError):
        resolve(schedule)


def test_overture_config_resolves_to_the_overture_command(events_dir):
    write_config(events_dir, "quake.yaml", OVERTURE_CONFIG, frequency="daily")
    jobs, _ = resolve({"groups": ["events"], "events": {"dir": "configs/events"}})
    assert [(job.command, job.id) for job in jobs] == [("overture", "events/quake")]


def test_a_config_enabling_both_sources_becomes_two_jobs(events_dir):
    write_config(events_dir, "quake.yaml", BOTH_CONFIG, frequency="daily")
    jobs, _ = resolve({"groups": ["events"], "events": {"dir": "configs/events"}})
    assert [(job.command, job.id) for job in jobs] == [
        ("osm", "events/quake:osm"),
        ("overture", "events/quake:overture"),
    ]


def test_a_source_block_that_omits_a_key_keeps_the_oex_default(events_dir):
    write_config(events_dir, "quake.yaml", "iso3: NPL\nsource:\n  pcodes:\n    enabled: true\n")
    jobs, _ = resolve({"groups": ["events"], "events": {"dir": "configs/events", "frequency": "d"}})
    assert [job.command for job in jobs] == ["osm", "overture"]


def test_a_config_without_a_source_block_is_an_error(events_dir):
    write_config(events_dir, "quake.yaml", "iso3: NPL\n", frequency="daily")
    with pytest.raises(sweep.ScheduleError):
        resolve({"groups": ["events"], "events": {"dir": "configs/events"}})


def test_a_config_with_every_source_disabled_is_an_error(events_dir):
    body = "iso3: NPL\nsource:\n  osm:\n    enabled: false\n  overture:\n    enabled: false\n"
    write_config(events_dir, "quake.yaml", body, frequency="daily")
    with pytest.raises(sweep.ScheduleError):
        resolve({"groups": ["events"], "events": {"dir": "configs/events"}})


def test_no_hdx_push_reaches_every_command_line():
    jobs, _ = sweep.resolve(
        countries_schedule({"NPL": "monthly"}), None, None, TODAY, ("--no-hdx-push",)
    )
    assert jobs[0].argv()[-1] == "--no-hdx-push"


def test_a_country_without_an_override_uses_base_directly():
    jobs, _ = resolve(countries_schedule({"NPL": "monthly"}))
    assert jobs[0].config == sweep.BASE_CONFIG
    assert jobs[0].iso3 == "NPL"


def test_a_country_override_is_merged_over_base_not_substituted(tmp_path, monkeypatch):
    """The override must not silently drop hdx.push, S3 and the HOT category list."""
    overrides = tmp_path / "countries"
    overrides.mkdir()
    (overrides / "SDN.yaml").write_text("dataset_name: Sudan\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "COUNTRY_CONFIG_DIR", overrides)
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")

    merged = yaml.safe_load(sweep.country_config("SDN").read_text(encoding="utf-8"))
    base = yaml.safe_load(sweep.BASE_CONFIG.read_text(encoding="utf-8"))
    assert merged["dataset_name"] == "Sudan"
    assert merged["hdx"]["push"] == base["hdx"]["push"]
    assert merged["categories_file"] == base["categories_file"]
    assert "${oc.env:HDX_API_KEY}" in merged["hdx"]["api_key"]


def test_a_merged_country_config_loads_the_same_way_base_does(tmp_path, monkeypatch):
    for name in ("OEX_S3_BUCKET", "HDX_API_KEY", "HDX_OWNER_ORG", "HDX_MAINTAINER"):
        monkeypatch.setenv(name, "test")
    overrides = tmp_path / "countries"
    overrides.mkdir()
    (overrides / "SDN.yaml").write_text("dataset_name: Sudan\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "COUNTRY_CONFIG_DIR", overrides)
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")

    base = load_config(sweep.BASE_CONFIG)
    merged = load_config(sweep.country_config("SDN"))
    assert merged.hdx.push == base.hdx.push is True
    assert merged.output.s3.enabled == base.output.s3.enabled is True
    assert len(merged.categories) == len(base.categories)
    assert merged.dataset_name == "Sudan"


class StubJob:
    def __init__(self, job_id, argv):
        self.id = job_id
        self._argv = argv

    def argv(self):
        return self._argv


def test_a_failing_job_is_reported_and_the_sweep_continues(capsys):
    jobs = [StubJob("a", ["false"]), StubJob("b", ["true"])]
    assert sweep.run_jobs(jobs, timeout=30) == ["a"]
    assert "[2/2] b" in capsys.readouterr().out


def test_a_job_that_overruns_its_timeout_is_a_failure(capsys):
    assert sweep.run_jobs([StubJob("slow", ["sleep", "5"])], timeout=1) == ["slow"]
    assert "TIMEOUT" in capsys.readouterr().err


def test_a_second_sweep_cannot_take_the_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path)
    held = sweep.acquire_lock()
    assert held is not None
    assert sweep.acquire_lock() is None
    held.close()
    assert sweep.acquire_lock() is not None


def test_the_shipped_schedule_resolves():
    schedule = yaml.safe_load(sweep.SCHEDULE_FILE.read_text(encoding="utf-8"))
    jobs, _ = resolve(schedule, frequency="monthly")
    assert len(jobs) == 248
    assert all(job.command == "osm" for job in jobs)
