#!/usr/bin/env -S uv run python
"""Print ISO3 codes from scripts/countries.yaml, one per line.

Usage:
    list_countries.py                    every country, priority->normal->big order
    list_countries.py all                same as no arg
    list_countries.py priority           countries tagged group=priority
    list_countries.py normal             countries tagged group=normal
    list_countries.py big                countries tagged group=big
    list_countries.py daily              countries tagged schedule=daily
    list_countries.py weekly             countries tagged schedule=weekly
    list_countries.py monthly            countries tagged schedule=monthly

For a cadence name, a disabled schedule prints a skip line to stderr and
exits 0 with no output, so a cron-driven sweep becomes a no-op.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

COUNTRIES_FILE = Path(__file__).parent / "countries.yaml"
GROUPS = ("priority", "normal", "big")
SCHEDULES = ("daily", "weekly", "monthly")
GROUP_RANK = {g: i for i, g in enumerate(GROUPS)}


def codes_for(name: str, data: dict) -> list[str]:
    countries: dict[str, dict[str, str]] = data.get("countries") or {}
    schedules: dict[str, dict] = data.get("schedule") or {}

    if name == "all":
        return sorted(countries, key=lambda iso: GROUP_RANK[countries[iso]["group"]])

    if name in GROUPS:
        return [iso for iso, meta in countries.items() if meta["group"] == name]

    if name in SCHEDULES:
        if not schedules.get(name, {}).get("enabled", True):
            print(f"schedule {name} disabled, nothing to do", file=sys.stderr)
            return []
        members = [iso for iso, meta in countries.items() if meta["schedule"] == name]
        return sorted(members, key=lambda iso: GROUP_RANK[countries[iso]["group"]])

    print(f"unknown name: {name}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "all"
    data = yaml.safe_load(COUNTRIES_FILE.read_text()) or {}
    for code in codes_for(name, data):
        print(code)


if __name__ == "__main__":
    main()
