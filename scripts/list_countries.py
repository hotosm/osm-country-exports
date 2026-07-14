#!/usr/bin/env -S uv run python
"""Print ISO3 codes from scripts/countries.yaml, one per line.

Order is hardcoded: priority -> normal -> big. A group with enabled: false
is skipped entirely.

Usage:
    list_countries.py                   every enabled country
    list_countries.py all               same as no arg
    list_countries.py priority          just the priority group
    list_countries.py normal            just the normal group
    list_countries.py big               just the big group
    list_countries.py daily             countries tagged cadence=daily
    list_countries.py weekly            countries tagged cadence=weekly
    list_countries.py monthly           countries tagged cadence=monthly
"""

import sys
from pathlib import Path

import yaml

COUNTRIES_FILE = Path(__file__).parent / "countries.yaml"
GROUPS = ("priority", "normal", "big")
CADENCES = ("daily", "weekly", "monthly")


def members(group: str, data: dict) -> dict[str, str]:
    cfg = data.get(group) or {}
    if not cfg.get("enabled", True):
        print(f"group {group} disabled, skipping", file=sys.stderr)
        return {}
    return cfg.get("countries") or {}


def codes_for(name: str, data: dict) -> list[str]:
    if name == "all":
        return [iso for g in GROUPS for iso in members(g, data)]
    if name in GROUPS:
        return list(members(name, data))
    if name in CADENCES:
        return [
            iso
            for g in GROUPS
            for iso, cadence in members(g, data).items()
            if cadence == name
        ]
    print(f"unknown name: {name}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "all"
    data = yaml.safe_load(COUNTRIES_FILE.read_text()) or {}
    for code in codes_for(name, data):
        print(code)


if __name__ == "__main__":
    main()
