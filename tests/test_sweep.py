import sys
import threading
import time
from datetime import date
from pathlib import Path

import pytest
import yaml
from oex.config.loader import load_config

import sweep

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


def test_no_hdx_push_reaches_every_command_line(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")
    jobs, _ = sweep.resolve(
        countries_schedule({"NPL": "monthly"}), None, None, TODAY, ("--no-hdx-push",)
    )
    assert jobs[0].argv()[-1] == "--no-hdx-push"


def test_a_country_without_an_override_still_gets_a_merged_config(tmp_path, monkeypatch):
    """Every job carries its schedule frequency, which oex publishes to HDX."""
    monkeypatch.setattr(sweep, "COUNTRY_CONFIG_DIR", tmp_path / "countries")
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")
    jobs, _ = resolve(countries_schedule({"NPL": "weekly"}))
    assert jobs[0].iso3 == "NPL"
    assert jobs[0].config != sweep.BASE_CONFIG
    assert yaml.safe_load(jobs[0].config.read_text(encoding="utf-8"))["frequency"] == "weekly"


def test_a_country_override_is_merged_over_base_not_substituted(tmp_path, monkeypatch):
    """The override must not silently drop hdx.push, S3 and the HOT category list."""
    overrides = tmp_path / "countries"
    overrides.mkdir()
    (overrides / "SDN.yaml").write_text("dataset_name: Sudan\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "COUNTRY_CONFIG_DIR", overrides)
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")

    merged = yaml.safe_load(sweep.country_config("SDN", "weekly").read_text(encoding="utf-8"))
    base = yaml.safe_load(sweep.BASE_CONFIG.read_text(encoding="utf-8"))
    assert merged["dataset_name"] == "Sudan"
    assert merged["hdx"]["push"] == base["hdx"]["push"]
    assert merged["categories_file"] == base["categories_file"]
    assert "${oc.env:HDX_API_KEY}" in merged["hdx"]["api_key"]
    assert merged["frequency"] == "weekly"


def test_a_merged_country_config_loads_the_same_way_base_does(tmp_path, monkeypatch):
    for name in ("OEX_S3_BUCKET", "HDX_API_KEY", "HDX_OWNER_ORG", "HDX_MAINTAINER"):
        monkeypatch.setenv(name, "test")
    overrides = tmp_path / "countries"
    overrides.mkdir()
    (overrides / "SDN.yaml").write_text("dataset_name: Sudan\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "COUNTRY_CONFIG_DIR", overrides)
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")

    # The sweep always passes --iso3, and pcode tagging refuses a config without one.
    base = load_config(sweep.BASE_CONFIG, ["iso3=SDN"])
    merged = load_config(sweep.country_config("SDN", "monthly"), ["iso3=SDN"])
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
    assert "[2/2] b done" in capsys.readouterr().out


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


def test_the_shipped_schedule_resolves(tmp_path, monkeypatch):
    """An exact job count breaks on every legitimate schedule edit, so assert the shape."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")
    schedule = yaml.safe_load(sweep.SCHEDULE_FILE.read_text(encoding="utf-8"))
    jobs, skipped = resolve(schedule, frequency="monthly")
    assert jobs
    assert skipped == []
    assert all(job.command in sweep.COMMAND_SOURCES for job in jobs)
    country_jobs = [job for job in jobs if job.group != "events"]
    assert all(len(job.iso3) == 3 and job.iso3.isupper() for job in country_jobs)
    assert len({job.id for job in jobs}) == len(jobs)


def test_a_dir_group_skips_underscore_partials(tmp_path, monkeypatch):
    """A shared categories file is included by another config, not a job of its own."""
    folder = tmp_path / "events"
    folder.mkdir()
    (folder / "real.yaml").write_text(OSM_CONFIG, encoding="utf-8")
    (folder / "_shared-categories.yaml").write_text("categories: []\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "REPO_ROOT", tmp_path)
    schedule = {"groups": ["events"], "events": {"dir": "events", "frequency": "daily"}}
    jobs, _ = resolve(schedule, frequency="daily")
    assert [job.config.name for job in jobs] == ["real.yaml"]


def test_no_resume_reaches_the_oex_command(monkeypatch, tmp_path):
    """A stale snapshot label can make resume skip a country, so operators need an override."""
    seen = main_with(monkeypatch, tmp_path, ["--no-resume"], countries_schedule({"NPL": "monthly"}))
    assert seen["jobs"][0].argv()[-1] == "--no-resume"


def test_only_narrows_the_job_list(tmp_path, monkeypatch):
    """A multi-day sweep gets interrupted, and rerunning every country is not the fix."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")
    jobs, _ = resolve(countries_schedule({"NPL": "monthly", "SDN": "monthly", "TCD": "monthly"}))
    assert [j.iso3 for j in sweep.select_countries(jobs, "NPL,TCD")] == ["NPL", "TCD"]


def test_only_rejects_a_code_with_no_job(tmp_path, monkeypatch):
    """Silently running nothing would look like success on a resumed sweep."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")
    jobs, _ = resolve(countries_schedule({"NPL": "monthly"}))
    with pytest.raises(sweep.ScheduleError, match="VNM"):
        sweep.select_countries(jobs, "NPL,VNM")


def test_workers_bound_peak_concurrency(tmp_path, monkeypatch):
    """--workers jobs run at once while more are queued, and never more than that."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path)
    peak = 0
    running = 0
    lock = threading.Lock()

    def observe(job, timeout, capture_dir, progress):
        nonlocal peak, running
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.2)
        with lock:
            running -= 1
        return None

    monkeypatch.setattr(sweep, "run_job", observe)
    sweep.run_jobs([StubJob(f"j{i}", ["true"]) for i in range(8)], timeout=30, workers=3)
    assert peak == 3, f"peak concurrency was {peak}, expected 3"


def test_one_failing_job_does_not_stop_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path)
    jobs = [StubJob("bad", ["false"]), StubJob("good", ["true"]), StubJob("bad2", ["false"])]
    assert sorted(sweep.run_jobs(jobs, timeout=30, workers=2)) == ["bad", "bad2"]


def test_a_single_worker_writes_no_capture_files(tmp_path, monkeypatch):
    """One worker needs no per-job log; its output belongs on the sweep's stdout."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path)
    assert sweep.run_jobs([StubJob("a", ["true"])], timeout=30, workers=1) == []
    assert not (tmp_path / "logs").exists()


def test_parallel_workers_capture_each_job_separately(tmp_path, monkeypatch):
    """Four concurrent exports interleaved into one stream cannot be read afterwards."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path)
    sweep.run_jobs([StubJob("x/y", ["echo", "hello"])], timeout=30, workers=2)
    assert (tmp_path / "logs" / "x_y.log").read_text().strip() == "hello"


def test_the_memory_budget_is_divided_between_workers(monkeypatch):
    """oex gives every export its adaptive share of memory; concurrent ones must split it."""
    monkeypatch.setattr(sweep, "adaptive_parallel_resources", lambda: (1, 38))
    assert sweep.memory_gb_per_worker(1) == 38
    assert sweep.memory_gb_per_worker(4) == 9


def test_the_budget_never_drops_below_one_gb(monkeypatch):
    monkeypatch.setattr(sweep, "adaptive_parallel_resources", lambda: (1, 1))
    assert sweep.memory_gb_per_worker(8) == 1


def test_the_budget_reaches_the_merged_config(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "COUNTRY_CONFIG_DIR", tmp_path / "countries")
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")
    merged = yaml.safe_load(sweep.country_config("SDN", "monthly", 7).read_text(encoding="utf-8"))
    assert merged["parallel"]["memory_gb"] == 7


def test_no_budget_leaves_the_config_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "COUNTRY_CONFIG_DIR", tmp_path / "countries")
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")
    merged = yaml.safe_load(sweep.country_config("SDN", "monthly").read_text(encoding="utf-8"))
    assert "memory_gb" not in (merged.get("parallel") or {})


def test_an_unrunnable_job_does_not_discard_its_siblings(tmp_path, monkeypatch):
    """pool.map re-raises on iteration, which would throw away every other result."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path)
    jobs = [StubJob("missing", ["/nonexistent/binary"]), StubJob("fine", ["true"])]
    assert sweep.run_jobs(jobs, timeout=30, workers=2) == ["missing"]


def test_a_failure_names_the_log_that_holds_its_output(tmp_path, monkeypatch, capsys):
    """With output captured per job, a bare FAILED line leaves nowhere to look."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path)
    sweep.run_jobs([StubJob("bad", ["false"])], timeout=30, workers=2)
    assert "bad.log" in capsys.readouterr().err


def test_an_unwritable_log_directory_fails_one_job_not_the_sweep(tmp_path, monkeypatch):
    """The capture setup runs per job, so its errors belong to that job's handler."""
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs").chmod(0o500)
    try:
        jobs = [StubJob("a", ["true"]), StubJob("b", ["true"])]
        assert sorted(sweep.run_jobs(jobs, timeout=30, workers=2)) == ["a", "b"]
    finally:
        (tmp_path / "logs").chmod(0o700)


def main_with(monkeypatch, tmp_path, argv, schedule):
    """Drive main() end to end, returning the (jobs, timeout, workers) it would run."""
    schedule_file = tmp_path / "schedule.yaml"
    schedule_file.write_text(yaml.safe_dump(schedule), encoding="utf-8")
    monkeypatch.setattr(sweep, "SCHEDULE_FILE", schedule_file)
    monkeypatch.setattr(sweep, "COUNTRY_CONFIG_DIR", tmp_path / "countries")
    monkeypatch.setattr(sweep, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(sweep, "acquire_lock", lambda: object())
    monkeypatch.setattr(sys, "argv", ["sweep", *argv])
    seen = {}

    def record(jobs, timeout, workers):
        seen.update(jobs=jobs, timeout=timeout, workers=workers)
        return []

    monkeypatch.setattr(sweep, "run_jobs", record)
    assert sweep.main() == 0
    return seen


def test_only_narrows_the_run_to_the_named_countries(monkeypatch, tmp_path):
    seen = main_with(
        monkeypatch,
        tmp_path,
        ["--only", "NPL"],
        countries_schedule({"NPL": "monthly", "HTI": "monthly", "CHL": "monthly"}),
    )
    assert [job.iso3 for job in seen["jobs"]] == ["NPL"]


def test_workers_reaches_run_jobs(monkeypatch, tmp_path):
    seen = main_with(
        monkeypatch, tmp_path, ["--workers", "3"], countries_schedule({"NPL": "monthly"})
    )
    assert seen["workers"] == 3


def test_more_than_one_worker_gives_each_country_a_memory_budget(monkeypatch, tmp_path):
    seen = main_with(
        monkeypatch, tmp_path, ["--workers", "4"], countries_schedule({"NPL": "monthly"})
    )
    merged = yaml.safe_load(Path(seen["jobs"][0].config).read_text(encoding="utf-8"))
    assert merged["parallel"]["memory_gb"] == sweep.memory_gb_per_worker(4)
