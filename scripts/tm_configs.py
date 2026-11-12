#!/usr/bin/env -S uv run python
"""Generate one oex config per active Tasking Manager project.

    tm_configs.py                       production projects, last 24h
    tm_configs.py --interval 6          a shorter window
    tm_configs.py --sandbox             sandbox projects, into their own group dir
    tm_configs.py --dry-run             report what would change, write nothing

Projects have no country code, so each config identifies by project id through
output.s3.folder and extracts from the planet PBF clipped to the project polygon.
Configs are never deleted: the API reports what moved in the interval, not
everything that exists.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

from oex.config.loader import load_config
from oex.config.schema import OsmSourceConfig
from oex.osm.runner import refresh_planet_pbf, refreshes_planet
from omegaconf import OmegaConf
from upath import UPath

from tasking_manager import TM_API, TaskingManagerError, fetch_json

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "configs" / "_tm-template.yaml"
MAX_INTERVAL_HOURS = 24
SANDBOX_PBF_ENV = "TM_SANDBOX_PBF"
# TM mapping_types are 1-based indexes into this order.
MAPPING_TYPES = ("Roads", "Buildings", "Waterways", "Landuse")
DATE_PREFIX = re.compile(r"\d{4}-\d{2}-\d{2}")


def _display(path: Path) -> str:
    """Repo-relative when it is inside the repo, never raising for --out elsewhere."""
    return os.path.relpath(path, REPO_ROOT)


def fetch_active_projects(interval: int, sandbox: bool, timeout: int) -> list[dict]:
    """Active projects as GeoJSON features. The endpoint caps interval at 24 hours."""
    if not 1 <= interval <= MAX_INTERVAL_HOURS:
        raise TaskingManagerError(f"--interval must be 1..{MAX_INTERVAL_HOURS}, got {interval}")
    url = f"{TM_API}/projects/queries/active/?interval={interval}"
    if sandbox:
        url += "&sandbox=true"
    payload = fetch_json(url, timeout)
    if "features" not in payload:
        raise TaskingManagerError(f"{url}: no `features` in the response: {payload}")
    return payload["features"]


def fetch_project(project_id: str, timeout: int) -> dict:
    """One project as a GeoJSON feature, whatever its recent activity."""
    url = f"{TM_API}/projects/{project_id}/"
    payload = fetch_json(url, timeout)
    if "areaOfInterest" not in payload:
        raise TaskingManagerError(f"{url}: no `areaOfInterest` in the response")
    return {
        "geometry": payload["areaOfInterest"],
        "properties": {
            "project_id": payload["projectId"],
            "mapping_types": payload.get("mappingTypes"),
        },
    }


def category_names(mapping_types: list | None) -> list[str]:
    """TM mapping types to template category names, dropping ones oex has no filter for.

    The API sends 1-based indexes; tm-extractor also accepts names like LAND_USE.
    """
    by_name = {name.upper(): name for name in MAPPING_TYPES}
    names = []
    for value in mapping_types or []:
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and 1 <= value <= len(MAPPING_TYPES):
            names.append(MAPPING_TYPES[value - 1])
        elif isinstance(value, str):
            match = by_name.get(value.upper().replace("_", ""))
            if match:
                names.append(match)
    return names


def build_config(
    template,
    feature: dict,
    pbf_path: Path | None = None,
    all_categories: bool = False,
):
    """Fill the template in for one project. Returns None when nothing maps.

    A caller-supplied template declares the categories it wants, so the project's
    mapping types only select from the default one."""
    project_id = feature["properties"]["project_id"]
    cfg = OmegaConf.create(OmegaConf.to_yaml(template, resolve=False))
    if not all_categories:
        wanted = category_names(feature["properties"].get("mapping_types"))
        if not wanted:
            return None
        cfg.categories = [c for c in cfg.categories if c.name in wanted]
    if not cfg.categories:
        return None
    cfg.dataset_name = f"Tasking Manager Project {project_id}"
    cfg.boundary.geom = json.dumps(feature["geometry"])
    cfg.output.s3.folder = f"hotosm_project_{project_id}"
    if pbf_path is not None:
        cfg.source.osm.pbf_path = str(pbf_path)
        # oex would otherwise date this file against the published planet and download over it.
        cfg.source.osm.auto_download_planet = False
    return cfg


def write_osmium_config(features: list[dict], pbf_dir: Path) -> tuple[Path, dict[str, Path]]:
    """One osmium extract config covering every project, so the source PBF is read once.

    osmium streams the whole input per invocation, so one pass with N extracts costs
    a single read instead of N. Returns the config path and project id -> output PBF.
    """
    pbf_dir.mkdir(parents=True, exist_ok=True)
    extracts, outputs = [], {}
    for feature in features:
        project_id = str(feature["properties"]["project_id"])
        polygon = pbf_dir / f"{project_id}.geojson"
        polygon.write_text(json.dumps(feature["geometry"]), encoding="utf-8")
        output = pbf_dir / f"{project_id}.osm.pbf"
        extracts.append(
            {
                "output": output.name,
                "polygon": {"file_name": str(polygon), "file_type": "geojson"},
            }
        )
        outputs[project_id] = output
    config = pbf_dir / "_osmium-extracts.json"
    config.write_text(
        json.dumps({"directory": str(pbf_dir), "extracts": extracts}, indent=2),
        encoding="utf-8",
    )
    return config, outputs


def run_osmium_extract(source_pbf: Path, config: Path) -> None:
    """Single pass over the source PBF, writing every project's extract."""
    command = [
        "osmium",
        "extract",
        "--config",
        str(config),
        "--strategy",
        "complete_ways",
        "--overwrite",
        str(source_pbf),
    ]
    print(f"osmium extract: one pass over {source_pbf} for {config}")
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise TaskingManagerError(f"osmium extract failed with rc={completed.returncode}")


def resolve_source_pbf(location: str) -> str:
    """A location ending in `/` is a prefix of dated folders; take the newest PBF in it.

    The sandbox publishes one export per day under `exports/<YYYY-MM-DD>/`, so the
    source moves daily and cannot be pinned in the environment.
    """
    if not location.endswith("/"):
        return location
    root = UPath(location)
    dated = sorted(child.name for child in root.iterdir() if DATE_PREFIX.fullmatch(child.name))
    if not dated:
        raise TaskingManagerError(f"{location}: no YYYY-MM-DD folders to pick a source from")
    newest = root / dated[-1]
    pbfs = sorted(child for child in newest.iterdir() if child.name.endswith(".pbf"))
    if not pbfs:
        raise TaskingManagerError(f"{newest}: no .pbf inside the newest folder")
    print(f"source: {pbfs[0]} (newest of {len(dated)} dated folders)")
    return str(pbfs[0])


def ensure_local_pbf(source: str, cache_dir: Path) -> Path:
    """osmium reads local files only, so fetch a remote source once and reuse it."""
    if "://" not in source:
        return Path(source)
    remote = UPath(source)
    cache_dir.mkdir(parents=True, exist_ok=True)
    local = cache_dir / f"{remote.parent.name}-{remote.name}"
    size = remote.stat().st_size
    if local.is_file() and local.stat().st_size == size:
        print(f"source: reusing {_display(local)}")
        return local
    print(f"source: downloading {source} ({size / 1e6:.1f} MB) -> {_display(local)}")
    local.write_bytes(remote.read_bytes())
    return local


def extract_source(template_path: Path, sandbox: bool) -> str:
    """Sandbox projects are mapped in their own database, exported to the location in the
    environment; production ones come from the template's planet, refreshed when outdated."""
    if sandbox:
        location = os.environ.get(SANDBOX_PBF_ENV)
        if not location:
            raise TaskingManagerError(f"sandbox extracts need {SANDBOX_PBF_ENV} set")
        return location
    osm = cast(OsmSourceConfig, load_config(template_path).source["osm"])
    if not osm.pbf_path:
        raise TaskingManagerError(f"{template_path}: source.osm.pbf_path is not set")
    if osm.engine.lower() == "planet" and refreshes_planet(osm):
        refresh_planet_pbf(osm, Path(osm.pbf_path))
    return osm.pbf_path


def cut_project_extracts(
    features: list[dict], source: str, target: Path
) -> tuple[dict[str, Path], Path]:
    """Cut every project's PBF in one pass. Returns the usable extracts, and the local source
    for a project osmium wrote nothing for."""
    source_pbf = ensure_local_pbf(resolve_source_pbf(source), target)
    if not source_pbf.is_file():
        raise TaskingManagerError(f"source PBF {source_pbf} is not a file")
    config, outputs = write_osmium_config(features, target)
    run_osmium_extract(source_pbf, config)

    usable = {}
    for project_id, path in outputs.items():
        if not path.is_file():
            print(f"warn project {project_id}: osmium wrote no extract, using {source_pbf} whole")
            continue
        if node_count(path) == 0:
            print(
                f"warn project {project_id}: extract is empty, so {source_pbf} does not cover it; "
                "the export would publish nothing"
            )
        usable[project_id] = path
    return usable, source_pbf


def node_count(pbf: Path) -> int:
    """Nodes in a PBF. Zero means the source did not cover that project's polygon."""
    completed = subprocess.run(
        ["osmium", "fileinfo", "-e", "-g", "data.count.nodes", str(pbf)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise TaskingManagerError(f"osmium fileinfo failed for {pbf}: {completed.stderr.strip()}")
    return int(completed.stdout.strip() or 0)


def sync(out_dir: Path, configs: dict, dry_run: bool) -> int:
    written = 0
    for name, cfg in sorted(configs.items()):
        text = OmegaConf.to_yaml(cfg, resolve=False)
        target = out_dir / name
        if target.exists() and target.read_text(encoding="utf-8") == text:
            continue
        written += 1
        if not dry_run:
            target.write_text(text, encoding="utf-8")

    return written


def export_configs(paths: list[Path]) -> int:
    """Run oex-cli over the configs just written. How often to do that is the caller's call."""
    failures = []
    for index, path in enumerate(paths, start=1):
        print(f"[{index}/{len(paths)}] export {_display(path)}", flush=True)
        completed = subprocess.run(
            ["uv", "run", "oex-cli", "osm", "--config", str(path)], cwd=REPO_ROOT
        )
        if completed.returncode != 0:
            print(f"[{index}/{len(paths)}] FAILED rc={completed.returncode}", file=sys.stderr)
            failures.append(path.name)
    if failures:
        print(f"{len(failures)}/{len(paths)} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"export complete {len(paths)}/{len(paths)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=MAX_INTERVAL_HOURS,
        help=f"hours of activity, 1..{MAX_INTERVAL_HOURS} (default 24); unused with --project",
    )
    parser.add_argument("--sandbox", action="store_true", help="sandbox projects")
    parser.add_argument("--out", type=Path, help="output dir (default: the group dir)")
    parser.add_argument("--timeout", type=int, default=60, help="API timeout, seconds")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument(
        "--extract",
        action="store_true",
        help="cut a per-project PBF in one osmium pass over the source PBF, and point "
        "each config at its own extract instead of the whole file",
    )
    parser.add_argument("--pbf-dir", type=Path, help="where --extract writes per-project PBFs")
    parser.add_argument(
        "--template", type=Path, default=TEMPLATE, help="config template to fill in per project"
    )
    parser.add_argument(
        "--project",
        action="append",
        metavar="ID",
        help="export these projects whatever their activity, ignoring --interval",
    )
    parser.add_argument(
        "--export", action="store_true", help="export each project after writing its config"
    )
    args = parser.parse_args()

    out_dir = args.out or REPO_ROOT / "configs" / (
        "tasking_manager_sandbox" if args.sandbox else "tasking_manager"
    )
    if not out_dir.is_dir():
        print(f"tm: {out_dir} is not a directory", file=sys.stderr)
        return 2
    if args.sandbox and not args.extract and not args.dry_run:
        print(
            f"tm: --sandbox needs --extract, since {SANDBOX_PBF_ENV} names a folder of dated "
            "exports rather than one file",
            file=sys.stderr,
        )
        return 2

    template = OmegaConf.create(args.template.read_text(encoding="utf-8"))
    try:
        if args.project:
            features = [fetch_project(pid, args.timeout) for pid in args.project]
        else:
            features = fetch_active_projects(args.interval, args.sandbox, args.timeout)

        kept = []
        for feature in features:
            if category_names(feature["properties"].get("mapping_types")):
                kept.append(feature)
            else:
                print(
                    f"skip project {feature['properties']['project_id']}: no supported mapping type"
                )

        outputs: dict[str, Path] = {}
        source_pbf = None
        if args.extract and kept and not args.dry_run:
            group = "tm_sandbox" if args.sandbox else "tm"
            pbf_dir = (
                args.pbf_dir or Path(os.environ.get("OEX_DATA_DIR", REPO_ROOT)) / "data" / group
            )
            source = extract_source(args.template, args.sandbox)
            outputs, source_pbf = cut_project_extracts(kept, source, pbf_dir)
    except TaskingManagerError as error:
        print(f"tm: {error}", file=sys.stderr)
        return 2

    configs = {}
    for feature in kept:
        project_id = str(feature["properties"]["project_id"])
        cfg = build_config(
            template,
            feature,
            outputs.get(project_id, source_pbf),
            args.template != TEMPLATE,
        )
        if cfg is None:
            print(f"skip project {project_id}: no category matched")
            continue
        configs[f"{project_id}.yaml"] = cfg

    written = sync(out_dir, configs, args.dry_run)
    scope = "sandbox" if args.sandbox else "production"
    print(
        f"tm: {scope} active={len(features)} configs={len(configs)} "
        f"written={written} -> {_display(out_dir)}"
    )
    if not args.export or args.dry_run:
        return 0
    return export_configs([out_dir / name for name in sorted(configs)])


if __name__ == "__main__":
    sys.exit(main())
