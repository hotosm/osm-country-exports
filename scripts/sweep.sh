#!/usr/bin/env bash
# Sweep oex over scripts/countries.yaml. Run from the repo root.
#
# Usage:
#   scripts/sweep.sh                  every country (priority -> normal -> big)
#   scripts/sweep.sh priority         one ordering group
#   scripts/sweep.sh daily            one cron cadence
set -euo pipefail

group="${1:-all}"

if ! iso3_raw=$(scripts/list_countries.py "$group"); then
    echo "sweep: list_countries.py $group failed" >&2
    exit 2
fi

if [ -z "$iso3_raw" ]; then
    echo "sweep: group=$group empty, nothing to do"
    exit 0
fi

mapfile -t iso3_list <<< "$iso3_raw"
total=${#iso3_list[@]}

echo "sweep: group=$group countries=$total"

failures=0
idx=0
for iso in "${iso3_list[@]}"; do
    idx=$((idx + 1))
    override="configs/countries/${iso}.yaml"
    config="configs/base.yaml"
    [ -f "$override" ] && config="$override"

    echo "[$idx/$total] $iso config=$config"
    if ! uv run oex-cli osm --config "$config" --iso3 "$iso"; then
        echo "[$idx/$total] $iso FAILED" >&2
        failures=$((failures + 1))
    fi
done

if [ "$failures" -gt 0 ]; then
    echo "sweep: $failures/$total failed" >&2
    exit 1
fi

echo "sweep: complete $total/$total"
