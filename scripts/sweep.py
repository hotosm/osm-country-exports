#!/usr/bin/env -S uv run python
"""Resolve scripts/schedule.yaml into oex-cli jobs and run them.

    sweep.py                                        every enabled job
    sweep.py --group priority --frequency monthly   one group at one frequency
    sweep.py --frequency "as needed"                the manual-only jobs
    sweep.py --dry-run                              print the commands, run nothing
    sweep.py --json                                 print the job list, run nothing

Exit codes: 1 a job failed, 2 the schedule is malformed, 3 another sweep holds the lock.
"""

import argparse
import fcntl
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
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


def country_config(iso3: str) -> Path:
    """configs/countries/<ISO3>.yaml merged over base, or base alone.

    Interpolations stay unresolved, so no secret reaches the merged file.
    """
    override = COUNTRY_CONFIG_DIR / f"{iso3}.yaml"
    if not override.exists():
        return BASE_CONFIG
    merged = OmegaConf.merge(OmegaConf.load(BASE_CONFIG), OmegaConf.load(override))
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
    for config in sorted(folder.glob("*.yaml")):
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

            config = country_config(str(ref)) if kind == "country" else Path(str(ref))
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


def run_jobs(jobs: list[Job], timeout: int) -> list[str]:
    failures = []
    total = len(jobs)
    for index, job in enumerate(jobs, start=1):
        print(f"[{index}/{total}] {job.id}: {' '.join(job.argv())}", flush=True)
        try:
            completed = subprocess.run(job.argv(), cwd=REPO_ROOT, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(
                f"[{index}/{total}] {job.id} TIMEOUT after {timeout}s", file=sys.stderr, flush=True
            )
            failures.append(job.id)
            continue
        if completed.returncode != 0:
            print(
                f"[{index}/{total}] {job.id} FAILED rc={completed.returncode}",
                file=sys.stderr,
                flush=True,
            )
            failures.append(job.id)
    return failures


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
    args = parser.parse_args()

    extra = ("--no-hdx-push",) if args.no_hdx_push else ()
    schedule = yaml.safe_load(SCHEDULE_FILE.read_text(encoding="utf-8")) or {}
    try:
        jobs, skipped = resolve(schedule, args.group, args.frequency, date.today(), extra)
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

    failures = run_jobs(jobs, args.timeout)
    if failures:
        print(f"sweep: {len(failures)}/{len(jobs)} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"sweep: complete {len(jobs)}/{len(jobs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
