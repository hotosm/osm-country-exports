#!/usr/bin/env -S uv run python
"""Align the expected update frequency of published HDX datasets with the schedule.

A sweep sets the frequency when it publishes, so datasets only drift when the
schedule changes and the group has not run since. This resets them without
re-exporting anything.

    sync_hdx_frequency.py --group heavy              # report the drift, change nothing
    sync_hdx_frequency.py --group heavy --apply      # write the new frequency
    sync_hdx_frequency.py                            # every country group

Exit codes: 1 a dataset failed to update, 2 the schedule is malformed.
"""

import argparse
import os
import sys
from pathlib import Path

import yaml
from hdx.api.configuration import Configuration
from hdx.data.dataset import Dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_FILE = REPO_ROOT / "scripts" / "schedule.yaml"
BASE_CONFIG = REPO_ROOT / "configs" / "base.yaml"
COUNTRY_CONFIG_DIR = REPO_ROOT / "configs" / "countries"


def categories(schema_path: Path) -> list[str]:
    raw = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
    return [c["name"] for c in raw["categories"]]


def dataset_key(iso3: str, base: dict) -> str:
    """The `key` prefix oex builds dataset names from, honouring a country override."""
    override = COUNTRY_CONFIG_DIR / f"{iso3}.yaml"
    if override.exists():
        raw = yaml.safe_load(override.read_text(encoding="utf-8")) or {}
        if "key" in raw:
            return raw["key"]
    return base["key"]


def scheduled_countries(schedule: dict, group_filter: str | None) -> list[tuple[str, str]]:
    """(iso3, frequency) for every country in the schedule, disabled ones included.

    A disabled country still has datasets on HDX, and they should state the
    frequency the schedule declares.
    """
    pairs = []
    for name in schedule.get("groups", []):
        if group_filter is not None and name != group_filter:
            continue
        group = schedule.get(name) or {}
        if "countries" not in group:
            continue
        default = group.get("frequency")
        for iso3, value in (group["countries"] or {}).items():
            frequency = value if isinstance(value, str) else (value or {}).get("frequency", default)
            if frequency is None:
                raise SystemExit(f"{name}/{iso3}: no frequency here or on the group")
            pairs.append((iso3, frequency))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="one group from `groups:` in the schedule")
    parser.add_argument("--apply", action="store_true", help="write changes (default: report only)")
    args = parser.parse_args()

    schedule = yaml.safe_load(SCHEDULE_FILE.read_text(encoding="utf-8")) or {}
    base = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8")) or {}
    cats = categories(REPO_ROOT / base["categories_file"])
    pairs = scheduled_countries(schedule, args.group)
    print(f"{len(pairs)} country(ies) x {len(cats)} categories = {len(pairs) * len(cats)} datasets")

    api_key = os.environ.get("HDX_API_KEY")
    if not api_key:
        raise SystemExit("HDX_API_KEY is not set; source .env first")
    Configuration.create(
        hdx_site=base["hdx"]["site"],
        user_agent=base["hdx"]["user_agent"],
        hdx_key=api_key,
    )

    drift, missing, failed = [], 0, []
    for iso3, frequency in pairs:
        wanted = Dataset.transform_update_frequency(frequency)
        if wanted is None:
            raise SystemExit(f"{iso3}: {frequency!r} is not a frequency HDX understands")
        key = dataset_key(iso3, base)
        for slug in cats:
            name = f"{key}_{iso3.lower()}_{slug}"
            dataset = Dataset.read_from_hdx(name)
            if dataset is None:
                missing += 1
                continue
            current = str(dataset.get("data_update_frequency", ""))
            if current == wanted:
                continue
            drift.append((name, current, wanted))
            if not args.apply:
                continue
            try:
                dataset.set_expected_update_frequency(frequency)
                dataset.update_in_hdx(update_resources=False, hxl_update=False)
            except Exception as error:  # noqa: BLE001 - report and continue the sweep
                failed.append(f"{name}: {error}")

    label = Dataset.update_frequencies
    for name, current, wanted in drift:
        was = label.get(current, current or "unset")
        now = label.get(wanted, wanted)
        print(f"  {'updated' if args.apply else 'would set'} {name}: {was} -> {now}")

    print(
        f"\n{len(drift)} drifted, {len(pairs) * len(cats) - len(drift) - missing} already correct, "
        f"{missing} not published"
    )
    if failed:
        print(f"{len(failed)} failed:", file=sys.stderr)
        for line in failed:
            print(f"  {line}", file=sys.stderr)
        return 1
    if drift and not args.apply:
        print("re-run with --apply to write these")
    return 0


if __name__ == "__main__":
    sys.exit(main())
