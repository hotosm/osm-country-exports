#!/usr/bin/env -S uv run python
"""Resolve scripts/schedule.yaml into oex-cli jobs and run them.

    sweep.py                                        every enabled job
    sweep.py --group priority --frequency monthly   one group at one frequency
    sweep.py --frequency "as needed"                the manual-only jobs
    sweep.py --dry-run                              print the commands, run nothing
    sweep.py --json                                 print the job list, run nothing
    sweep.py --group priority --no-resume           re-export even if state says done
    sweep.py --group normal --only ZWE,VNM          just those countries
    sweep.py --group normal --workers 4             four countries at once

With --workers above 1 each job's output goes to .sweep/logs/<job-id>.log.

Exit codes: 1 a job failed, 2 the schedule is malformed, 3 another sweep holds the lock.
"""

import argparse
import fcntl
import json
import subprocess
import sys
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

import yaml
from oex.system import adaptive_parallel_resources
from omegaconf import OmegaConf

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_FILE = REPO_ROOT / "scripts" / "schedule.yaml"
BASE_CONFIG = REPO_ROOT / "configs" / "base.yaml"
COUNTRY_CONFIG_DIR = REPO_ROOT / "configs" / "countries"
WORK_DIR = REPO_ROOT / ".sweep"
MANUAL_FREQUENCY = "as needed"
COMMAND_SOURCES = ("osm", "overture")
DEFAULT_TIMEOUT_SECONDS = 6 * 60 * 60


class ScheduleError(Exception):
    """The schedule, or a config it points at, is malformed."""


class Runnable(Protocol):
    @property
    def id(self) -> str: ...

    def argv(self) -> list[str]: ...


@dataclass(frozen=True)
class Job:
    id: str
    group: str
    command: str
    config: Path
    iso3: str | None
    extra: tuple[str, ...] = ()

    def argv(self) -> list[str]:
        argv = ["uv", "run", "oex-cli", self.command, "--config", str(self.config)]
        if self.iso3:
            argv += ["--iso3", self.iso3]
        return argv + list(self.extra)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "group": self.group,
            "command": self.command,
            "config": str(self.config.relative_to(REPO_ROOT)),
            "iso3": self.iso3,
            "argv": self.argv(),
        }


def attributes(value: object, default_frequency: str | None) -> dict:
    """Normalise a schedule value: either a bare frequency or a mapping."""
    if value is None:
        attrs: dict = {}
    elif isinstance(value, str):
        attrs = {"frequency": value}
    elif isinstance(value, dict):
        attrs = dict(value)
    else:
        raise ScheduleError(f"expected a frequency or a mapping, got {value!r}")
    attrs.setdefault("frequency", default_frequency)
    attrs.setdefault("enabled", True)
    return attrs


def expiry_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def skip_reason(attrs: dict, frequency_filter: str | None, today: date) -> str | None:
    """Why a job that matched the filters still will not run."""
    if not attrs["enabled"]:
        return "disabled"
    expires = attrs.get("expires")
    if expires is not None and today > expiry_date(expires):
        return f"expired {expires}"
    if frequency_filter is None and attrs["frequency"] == MANUAL_FREQUENCY:
        return f'manual, run it with --frequency "{MANUAL_FREQUENCY}"'
    return None


def memory_gb_per_worker(workers: int) -> int:
    """Concurrent exports would each size themselves from the whole machine, so they divide
    oex's adaptive share between them; the split replaces a country's own memory_gb."""
    _, memory_gb = adaptive_parallel_resources()
    return max(1, memory_gb // workers)


def country_config(iso3: str, frequency: str, memory_gb: int | None = None) -> Path:
    """configs/countries/<ISO3>.yaml merged over base, with the schedule's frequency.

    The frequency is written in last because oex passes it to HDX as the expected
    update frequency, so a dataset advertises the cadence that actually runs it.
    Interpolations stay unresolved, so no secret reaches the merged file.
    """
    layers = [OmegaConf.load(BASE_CONFIG)]
    override = COUNTRY_CONFIG_DIR / f"{iso3}.yaml"
    if override.exists():
        layers.append(OmegaConf.load(override))
    layers.append(OmegaConf.create({"frequency": frequency}))
    if memory_gb is not None:
        layers.append(OmegaConf.create({"parallel": {"memory_gb": memory_gb}}))
    merged = OmegaConf.merge(*layers)
    target = WORK_DIR / "merged" / f"{iso3}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(OmegaConf.to_yaml(merged, resolve=False), encoding="utf-8")
    return target


def commands_for(config: Path) -> list[str]:
    """Which oex-cli subcommands a config needs. Both sources enabled means both."""
    raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    source = raw.get("source")
    if source is None:
        raise ScheduleError(f"{config}: no `source:` block, cannot tell osm from overture apart")
    commands = [name for name in COMMAND_SOURCES if (source.get(name) or {}).get("enabled", True)]
    if not commands:
        raise ScheduleError(f"{config}: neither source.osm nor source.overture is enabled")
    return commands


def folder_candidates(name: str, group: dict) -> list[tuple[str, dict, str, object]]:
    folder = REPO_ROOT / group["dir"]
    if not folder.is_dir():
        raise ScheduleError(f"group {name!r}: {folder} is not a directory")
    overrides = group.get("overrides") or {}
    candidates = []
    # A leading underscore marks a partial included by another config, not a job.
    for config in sorted(folder.glob("[!_]*.yaml")):
        raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        default = raw.get("frequency") or group.get("frequency")
        candidates.append(
            (config.stem, attributes(overrides.get(config.name), default), "config", config)
        )
    return candidates


def group_candidates(name: str, group: dict) -> list[tuple[str, dict, str, object]]:
    """(label, attrs, kind, ref) for every job in a group, before filtering."""
    if "countries" in group:
        default = group.get("frequency")
        return [
            (iso3, attributes(value, default), "country", iso3)
            for iso3, value in (group["countries"] or {}).items()
        ]
    if "dir" in group:
        return folder_candidates(name, group)
    raise ScheduleError(f"group {name!r} has neither `countries:` nor `dir:`")


def resolve(
    schedule: dict,
    group_filter: str | None,
    frequency_filter: str | None,
    today: date,
    extra: tuple[str, ...] = (),
    memory_gb: int | None = None,
) -> tuple[list[Job], list[str]]:
    groups = schedule.get("groups")
    if not groups:
        raise ScheduleError("schedule has no `groups:` list")
    if group_filter is not None and group_filter not in groups:
        raise ScheduleError(f"unknown group {group_filter!r}, known: {', '.join(groups)}")

    jobs: list[Job] = []
    skipped: list[str] = []
    for name in groups:
        if group_filter is not None and name != group_filter:
            continue
        group = schedule.get(name)
        if group is None:
            raise ScheduleError(f"group {name!r} is listed in `groups:` but has no block")
        if not group.get("enabled", True):
            skipped.append(f"{name}: group disabled")
            continue

        for label, attrs, kind, ref in group_candidates(name, group):
            if attrs["frequency"] is None:
                raise ScheduleError(f"{name}/{label}: no frequency here or on the group")
            if frequency_filter is not None and attrs["frequency"] != frequency_filter:
                continue
            reason = skip_reason(attrs, frequency_filter, today)
            if reason is not None:
                skipped.append(f"{name}/{label}: {reason}")
                continue

            config = (
                country_config(str(ref), attrs["frequency"], memory_gb)
                if kind == "country"
                else Path(str(ref))
            )
            iso3 = str(ref) if kind == "country" else None
            commands = commands_for(config)
            for command in commands:
                suffix = f":{command}" if len(commands) > 1 else ""
                jobs.append(Job(f"{name}/{label}{suffix}", name, command, config, iso3, extra))
    return jobs, skipped


def acquire_lock():
    """Non-blocking exclusive lock, so an overrunning tick cannot collide with the next."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    handle = (WORK_DIR / "sweep.lock").open("w", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def select_countries(jobs: list[Job], only: str) -> list[Job]:
    """Narrow a resolved job list to the named ISO3 codes, for finishing a long sweep."""
    wanted = {code.strip().upper() for code in only.split(",") if code.strip()}
    unknown = wanted - {job.iso3 for job in jobs if job.iso3}
    if unknown:
        raise ScheduleError(f"--only names no job for {sorted(unknown)}")
    return [job for job in jobs if job.iso3 in wanted]


class Progress:
    """Counts completions, so the running total is right when jobs finish out of order."""

    def __init__(self, total: int):
        self._total = total
        self._done = 0
        self._lock = threading.Lock()

    def tick(self) -> str:
        with self._lock:
            self._done += 1
            return f"[{self._done}/{self._total}]"


def run_job(
    job: Runnable, timeout: int, capture_dir: Path | None, progress: Progress
) -> str | None:
    """Returns the job id when it fails, None when it succeeds."""
    print(f"{job.id}: starting", flush=True)
    log_file = None
    log_hint = ""
    try:
        if capture_dir is not None:
            capture_dir.mkdir(parents=True, exist_ok=True)
            log_path = capture_dir / f"{job.id.replace('/', '_')}.log"
            log_file = log_path.open("w", encoding="utf-8")
            log_hint = f", see {log_path}"
        completed = subprocess.run(
            job.argv(), cwd=REPO_ROOT, timeout=timeout, stdout=log_file, stderr=log_file
        )
    except subprocess.TimeoutExpired:
        print(f"{progress.tick()} {job.id} TIMEOUT after {timeout}s{log_hint}", file=sys.stderr)
        return job.id
    except OSError as error:
        # One unrunnable job must not discard the results of the jobs beside it.
        print(f"{progress.tick()} {job.id} FAILED {error}{log_hint}", file=sys.stderr)
        return job.id
    finally:
        if log_file is not None:
            log_file.close()
    if completed.returncode != 0:
        print(
            f"{progress.tick()} {job.id} FAILED rc={completed.returncode}{log_hint}",
            file=sys.stderr,
        )
        return job.id
    print(f"{progress.tick()} {job.id} done", flush=True)
    return None


def run_jobs(jobs: Sequence[Runnable], timeout: int, workers: int = 1) -> list[str]:
    progress = Progress(len(jobs))
    if workers == 1:
        return [r for job in jobs if (r := run_job(job, timeout, None, progress)) is not None]

    capture_dir = WORK_DIR / "logs"
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda job: run_job(job, timeout, capture_dir, progress), jobs)
    return [r for r in results if r is not None]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--group", help="one group from `groups:` in the schedule")
    parser.add_argument("--frequency", help="daily, weekly, monthly, or 'as needed'")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"per job, seconds (default {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    parser.add_argument("--json", action="store_true", help="print the job list, run nothing")
    parser.add_argument(
        "--no-hdx-push",
        action="store_true",
        help="rehearse against the real configs without publishing to HDX",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="run this many exports at once, each taking the next country as it frees up",
    )
    parser.add_argument(
        "--only",
        help="comma-separated ISO3 codes; run just these, for resuming a long sweep",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="re-export every category even if the state file says it is already uploaded",
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    extra = ("--no-hdx-push",) if args.no_hdx_push else ()
    if args.no_resume:
        extra += ("--no-resume",)
    schedule = yaml.safe_load(SCHEDULE_FILE.read_text(encoding="utf-8")) or {}
    try:
        memory_gb = memory_gb_per_worker(args.workers) if args.workers > 1 else None
        jobs, skipped = resolve(
            schedule, args.group, args.frequency, date.today(), extra, memory_gb
        )
    except ScheduleError as error:
        print(f"sweep: {error}", file=sys.stderr)
        return 2

    if args.workers > 1 and any(job.iso3 is None for job in jobs):
        print(
            "sweep: --workers above 1 only covers country groups; the memory budget "
            "cannot be set for a folder of standalone configs",
            file=sys.stderr,
        )
        return 2

    if args.only:
        try:
            jobs = select_countries(jobs, args.only)
        except ScheduleError as error:
            print(f"sweep: {error}", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps([job.as_dict() for job in jobs]))
        return 0

    for line in skipped:
        print(f"skip {line}")
    print(f"sweep: {len(jobs)} job(s)")

    if args.dry_run:
        for job in jobs:
            print(" ".join(job.argv()))
        return 0
    if not jobs:
        return 0

    lock = acquire_lock()
    if lock is None:
        print("sweep: another sweep holds the lock, refusing to overlap", file=sys.stderr)
        return 3

    failures = run_jobs(jobs, args.timeout, args.workers)
    if failures:
        print(f"sweep: {len(failures)}/{len(jobs)} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"sweep: complete {len(jobs)}/{len(jobs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
