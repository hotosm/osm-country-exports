#!/usr/bin/env -S uv run python
"""Print ISO3 codes from scripts/countries.yaml, one per line.

Usage:
    list_countries.py                  every group, in file order
    list_countries.py priority         one named group
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

COUNTRIES_FILE = Path(__file__).parent / "countries.yaml"


def codes_for(group: str, data: dict[str, list[str] | None]) -> list[str]:
    if group == "all":
        out: list[str] = []
        for codes in data.values():
            out.extend(codes or [])
        return out
    if group not in data:
        print(f"unknown group: {group}", file=sys.stderr)
        sys.exit(2)
    return data[group] or []


def main() -> None:
    group = sys.argv[1] if len(sys.argv) > 1 else "all"
    data = yaml.safe_load(COUNTRIES_FILE.read_text()) or {}
    for code in codes_for(group, data):
        print(code)


if __name__ == "__main__":
    main()
