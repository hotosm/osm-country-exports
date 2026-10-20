#!/usr/bin/env -S uv run python
"""Publish the project boundaries of a Tasking Manager campaign as one GeoJSON on HDX."""

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

import yaml
from oex.boundary import area_sq_km
from oex.config.loader import load_config
from oex.s3 import artifact_key
from oex.s3 import resolve as s3_resolve

from hdx_resource import HdxPublishError, attach_geojson, configure
from tasking_manager import TM_API, ProjectForbiddenError, TaskingManagerError, fetch_json

EPILOG = """examples:
  tm_campaign_boundaries.py --campaign "2026 Nepal Floods" --dataset hot_flood_npl --iso3 NPL
  tm_campaign_boundaries.py --campaigns-file configs/tm_campaigns.yaml
  tm_campaign_boundaries.py --campaign "..." --dataset ... --iso3 ... --dry-run
  tm_campaign_boundaries.py --campaign "..." --out boundaries.geojson

exit code 1: the Tasking Manager or HDX call failed, or the campaign matches no project."""

BASE_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "base.yaml"
TM_PROJECT_URL = "https://tasks.hotosm.org/projects/{id}"
# DRAFT projects are not public, so they are left out unless explicitly asked for.
DEFAULT_STATUSES = ("PUBLISHED", "ARCHIVED")
# What people read on HDX; the uploaded filename stays machine-friendly.
TM_RESOURCE_NAME = "Mapping Task Boundaries (Tasking Manager), GeoJSON"
DEFAULT_CATEGORY = "tasking_manager"
MAX_PAGES = 50
# bucket, prefix, region, endpoint_url, acl, as oex.s3.resolve returns them.
S3Settings = tuple[str, str, str, str | None, str]


class NoProjectsError(TaskingManagerError):
    """The campaign matched no project this run should publish."""


def fetch_campaign_projects(campaign: str, timeout: int, statuses: tuple[str, ...]) -> list[dict]:
    projects: list[dict] = []
    page = 1
    while page <= MAX_PAGES:
        # The search endpoint returns only PUBLISHED unless projectStatuses names the
        # rest, so an archived project would otherwise vanish from the campaign.
        url = (
            f"{TM_API}/projects/?campaign={urllib.parse.quote(campaign)}&page={page}"
            f"&projectStatuses={urllib.parse.quote(','.join(statuses))}"
        )
        payload = fetch_json(url, timeout)
        if "results" not in payload:
            raise TaskingManagerError(f"{url}: no `results` in the response")
        projects += payload["results"]
        expected = payload.get("pagination", {}).get("total")
        if not payload.get("pagination", {}).get("hasNext"):
            break
        page += 1
    else:
        raise TaskingManagerError(f"campaign {campaign!r}: more than {MAX_PAGES} pages")
    # A short read would publish a shrunken layer over a good one, so trust the count
    # the API reports rather than the rows that happened to arrive.
    if expected is not None and len(projects) != expected:
        raise TaskingManagerError(
            f"campaign {campaign!r}: API reported {expected} projects but returned {len(projects)}"
        )
    return [p for p in projects if p.get("status") in statuses]


def fetch_project_detail(project_id: int, timeout: int) -> dict:
    """The per-project payload: it alone carries the boundary, mapping types and creation date."""
    payload = fetch_json(f"{TM_API}/projects/{project_id}/", timeout)
    aoi = payload.get("areaOfInterest")
    if not aoi or not aoi.get("coordinates"):
        raise TaskingManagerError(f"project {project_id}: no areaOfInterest geometry")
    return payload


def build_feature(project: dict, detail: dict, campaign: str) -> dict:
    project_id = project["projectId"]
    geometry = detail["areaOfInterest"]
    return {
        "type": "Feature",
        "properties": {
            "project_id": project_id,
            "name": (project.get("name") or "").strip(),
            "campaign": campaign,
            "status": project.get("status"),
            "priority": project.get("priority"),
            "organisation": project.get("organisationName"),
            "mapping_types": detail.get("mappingTypes"),
            "percent_mapped": project.get("percentMapped"),
            "percent_validated": project.get("percentValidated"),
            "total_contributors": project.get("totalContributors"),
            "active_mappers": project.get("activeMappers"),
            "area_sq_km": round(area_sq_km(geometry), 2),
            "country": project.get("country"),
            "created": detail.get("created") or project.get("creationDate"),
            "last_updated": detail.get("lastUpdated") or project.get("lastUpdated"),
            "difficulty": project.get("difficulty"),
            "changeset_comment": detail.get("changesetComment"),
            "due_date": project.get("dueDate"),
            "project_url": TM_PROJECT_URL.format(id=project_id),
        },
        "geometry": geometry,
    }


def build_collection(campaign: str, timeout: int, statuses: tuple[str, ...]) -> dict:
    projects = fetch_campaign_projects(campaign, timeout, statuses)
    if not projects:
        raise NoProjectsError(f"campaign {campaign!r}: no projects with status in {statuses}")
    features = []
    for project in sorted(projects, key=lambda p: p["projectId"]):
        # A private project is not in an anonymous search, but a project can be made
        # private between the search and this call, and then answers 403.
        try:
            detail = fetch_project_detail(project["projectId"], timeout)
        except ProjectForbiddenError:
            print(f"  {project['projectId']:>7}  private, not published")
            continue
        features.append(build_feature(project, detail, campaign))
        print(
            f"  {project['projectId']:>7}  {project.get('status') or '':9s} "
            f"{project.get('percentMapped') or 0:3d}% mapped  "
            f"{(project.get('name') or '').strip()[:52]}"
        )
    if not features:
        raise NoProjectsError(f"campaign {campaign!r}: every matching project is private")

    return {"type": "FeatureCollection", "name": "tm_campaign_boundaries", "features": features}


def describe(campaign: str, collection: dict) -> str:
    """Resource description; the progress sentence depends on whether any project is still
    published."""
    features = collection["features"]
    statuses = sorted({f["properties"]["status"] for f in features})
    progress = (
        "Regenerated from the Tasking Manager API on each run, so the percentages track "
        "live progress."
        if any(f["properties"]["status"] == "PUBLISHED" for f in features)
        else "Every project in this campaign is archived, so the percentages are final."
    )
    return (
        f'Mapping task boundaries for the Tasking Manager campaign "{campaign}". '
        f"Status included: {', '.join(statuses)}. "
        "Each feature is one Tasking Manager project boundary and carries its id, name, "
        "status, priority, organisation, mapping types, completion percentages, contributor "
        "counts and a link to the project. "
        "This layer shows where volunteers have been asked to map, which is not the same as "
        "where data exists: a project at low completion marks a known gap rather than coverage. "
        f"{progress} "
        "Source: HOT Tasking Manager (https://tasks.hotosm.org/)."
    )


def publish(
    collection: dict,
    *,
    description: str,
    dataset_name: str,
    resource_name: str,
    file_name: str,
    iso3: str,
    category: str,
    s3_settings: S3Settings,
) -> None:
    bucket, prefix, region, endpoint_url, acl = s3_settings
    url = attach_geojson(
        collection,
        dataset_name=dataset_name,
        resource_name=resource_name,
        file_name=file_name,
        description=description,
        key=artifact_key(prefix, iso3, category, file_name),
        bucket=bucket,
        region=region,
        endpoint_url=endpoint_url,
        acl=acl,
    )
    print(f"\npublished {resource_name} -> {dataset_name}\n{url}")


def read_campaigns(campaigns_file: Path) -> dict:
    return yaml.safe_load(campaigns_file.read_text(encoding="utf-8")) or {}


def run_campaigns(
    campaigns: dict,
    *,
    timeout: int,
    statuses: tuple[str, ...],
    s3_settings: S3Settings | None,
) -> int:
    """Publish every enabled campaign, reporting each outcome. Without s3_settings
    nothing is published, which is a dry run."""
    failures = 0
    for campaign, entry in campaigns.items():
        entry = entry or {}
        if not entry.get("enabled", True):
            print(f"skip {campaign!r}: disabled")
            continue
        print(f"\ncampaign: {campaign}")
        missing = [field for field in ("dataset", "iso3") if not entry.get(field)]
        if missing:
            print(f"  FAILED {campaign!r}: no `{'`, `'.join(missing)}` set", file=sys.stderr)
            failures += 1
            continue
        dataset = entry["dataset"]
        resource = entry.get("resource") or TM_RESOURCE_NAME
        file_name = entry.get("file") or f"{dataset}_tm_projects.geojson"
        try:
            collection = build_collection(campaign, timeout, statuses)
            description = describe(campaign, collection)
            if s3_settings is None:
                print(f"  would publish {resource!r} ({file_name}) -> {dataset}\n  {description}")
                continue
            publish(
                collection,
                description=description,
                dataset_name=dataset,
                resource_name=resource,
                file_name=file_name,
                iso3=entry["iso3"],
                category=entry.get("category") or DEFAULT_CATEGORY,
                s3_settings=s3_settings,
            )
        except (TaskingManagerError, HdxPublishError) as error:
            # One bad campaign must not stop the others on a daily run.
            print(f"  FAILED {campaign!r}: {error}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


def configure_publishing() -> S3Settings:
    """HDX and S3 settings come from configs/base.yaml, so scripts and exports share them."""
    # base.yaml names no country, so pcode tagging, which needs one, is switched off to load it.
    cfg = load_config(BASE_CONFIG, ["source.pcodes.enabled=false"])
    configure(cfg.hdx.site, cfg.hdx.user_agent)
    return s3_resolve(cfg.output.s3)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--campaign", help="Tasking Manager campaign name, exact")
    source.add_argument(
        "--campaigns-file",
        type=Path,
        help="YAML of campaigns to publish, each with a dataset and iso3; runs all of them",
    )
    parser.add_argument("--dataset", help="HDX dataset to attach the resource to")
    parser.add_argument(
        "--resource-name",
        help=f'HDX display name, default "{TM_RESOURCE_NAME}"',
    )
    parser.add_argument(
        "--file-name", help="Uploaded filename, default <dataset>_tm_projects.geojson"
    )
    parser.add_argument("--iso3", help="S3 path segment")
    parser.add_argument("--category", help=f"S3 folder, default {DEFAULT_CATEGORY}")
    parser.add_argument(
        "--status",
        nargs="+",
        default=list(DEFAULT_STATUSES),
        help=f"project statuses to include, default {' '.join(DEFAULT_STATUSES)}",
    )
    parser.add_argument("--out", type=Path, help="write the GeoJSON here instead of publishing")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, publish nothing")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    single_only = ("out", "dataset", "resource_name", "file_name", "iso3", "category")
    if args.campaigns_file and any(getattr(args, name) for name in single_only):
        parser.error("--campaigns-file takes those settings per entry, not from the command line")
    if args.campaign and not args.out and not (args.dataset and args.iso3):
        parser.error("--dataset and --iso3 are required unless --out is given")

    statuses = tuple(args.status)
    if args.out:
        print(f"campaign: {args.campaign}")
        collection = build_collection(args.campaign, args.timeout, statuses)
        args.out.write_text(json.dumps(collection, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n{len(collection['features'])} project boundaries\nwrote {args.out}")
        return 0

    if args.campaigns_file:
        campaigns = read_campaigns(args.campaigns_file)
    else:
        campaigns = {
            args.campaign: {
                "dataset": args.dataset,
                "iso3": args.iso3,
                "resource": args.resource_name,
                "file": args.file_name,
                "category": args.category,
            }
        }
    return run_campaigns(
        campaigns,
        timeout=args.timeout,
        statuses=statuses,
        s3_settings=None if args.dry_run else configure_publishing(),
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (TaskingManagerError, HdxPublishError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
