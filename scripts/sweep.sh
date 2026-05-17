#!/usr/bin/env bash
# Sweep oex over scripts/countries.yaml.
#
# Usage:
#   ./scripts/sweep.sh                 all groups in order
#   ./scripts/sweep.sh priority        one named group
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

BASE_CONFIG="${OEX_BASE_CONFIG:-configs/base.yaml}"
GROUP="${1:-all}"

mapfile -t ISO3_LIST < <(scripts/list_countries.py "$GROUP")
TOTAL="${#ISO3_LIST[@]}"

echo "Sweep: group=$GROUP  countries=$TOTAL  base=$BASE_CONFIG"

idx=0
for iso in "${ISO3_LIST[@]}"; do
    idx=$((idx + 1))
    override="configs/countries/${iso}.yaml"
    config="$BASE_CONFIG"
    [ -f "$override" ] && config="$override"

    echo
    echo "----------------------------------------------------------------"
    echo "[$idx/$TOTAL] $iso  config=$config  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "----------------------------------------------------------------"

    uv run oex-cli osm --config "$config" --iso3 "$iso"
    echo "[$idx/$TOTAL] $iso exit=$?"
done

echo
echo "Sweep complete at $(date '+%Y-%m-%d %H:%M:%S')"
