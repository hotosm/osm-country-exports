#requirements:
#oex==0.4.1

"""Windmill entrypoint: export one country's OSM data via oex.

One country per run - the library equivalent of
`oex-cli osm --config <cfg> --iso3 <ISO3>`. Windmill builds the run form from
main()'s signature, and the dispatcher flow calls this once per country with
args pulled from scripts/countries.yaml.

Tag this script `heavy` in Windmill so it only runs on the high-memory pool.
"""

import os
from pathlib import Path

from oex.config.loader import apply_overrides, load_config, select_categories
from oex.exporter import Exporter
from oex.osm.runner import OsmRunner

# Where the repo lives on the worker (configs/ + _hot-schema.yaml). Baked into
# the heavy worker image; point OEX_REPO_DIR elsewhere to override.
REPO_DIR = Path(os.environ.get("OEX_REPO_DIR", "/opt/osm-country-exports"))


def _resolve_config(iso3: str, config_path: str) -> Path:
    """Explicit path wins, else the per-country override, else base.yaml.

    Same rule as scripts/sweep.sh.
    """
    if config_path:
        return Path(config_path)
    override = REPO_DIR / "configs" / "countries" / f"{iso3}.yaml"
    return override if override.exists() else REPO_DIR / "configs" / "base.yaml"


def main(
    iso3: str,
    priority: int = 50,        # queue priority (1-100); set on the job by the dispatcher
    cadence: str = "monthly",  # which schedule fired this run; metadata only
    hdx_push: bool = True,
    config_path: str = "",     # blank = auto-resolve (see _resolve_config)
    theme: str = "",           # optional single-theme run, e.g. "buildings"
    engine: str = "",          # optional OSM engine override: geofabrik | planet
    dataset_name: str = "",    # optional {country} label for HDX titles (e.g. "DRC")
):
    iso3 = iso3.upper()

    # oex resolves relative paths (categories_file, cache dirs) from the CWD,
    # exactly as the CLI does when run from the repo root.
    os.chdir(REPO_DIR)

    cfg_path = _resolve_config(iso3, config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"config not found: {cfg_path}")

    overrides: dict[str, object] = {"iso3": iso3, "hdx.push": hdx_push}
    if engine:
        overrides["source.osm.engine"] = engine
    if dataset_name:
        overrides["dataset_name"] = dataset_name

    cfg = load_config(cfg_path)
    cfg = apply_overrides(cfg, overrides)
    cfg = select_categories(cfg, theme or None)

    result = Exporter(cfg, OsmRunner()).run()

    summary = {
        "iso3": result.iso3,
        "source": result.source_name,
        "config": str(cfg_path),
        "priority": priority,
        "cadence": cadence,
        "succeeded": result.succeeded,
        "empty": result.empty,
        "skipped": result.skipped,
        "failed": result.failed,
        "duration_s": round(result.total_duration_s, 1),
    }

    # Fail the job (and the loop iteration) if any category failed, so it shows
    # red and is easy to re-run. "Continue on error" on the flow step keeps the
    # rest of the batch running.
    if result.failed:
        raise RuntimeError(f"{iso3}: {result.failed} categories failed - {summary}")

    return summary
