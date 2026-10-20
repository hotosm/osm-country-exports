#!/usr/bin/env -S uv run python
"""Publish the geometry a buffered extraction boundary was derived from, to HDX."""

import argparse
import json
import sys
from pathlib import Path

from oex.boundary import area_sq_km
from oex.config.loader import load_config
from oex.naming import COMBINED_SLUG, combined_dataset_name
from oex.s3 import artifact_key
from oex.s3 import resolve as s3_resolve

from hdx_resource import HdxPublishError, attach_geojson, configure

EPILOG = """examples:
  publish_source_geometry.py --config configs/events/NPL-FL-2026-flood-extent.yaml \\
      --name "Flood Extent, Observed 27 August 2026, GeoJSON"

oex publishes the buffered boundary as the Area of Interest; this publishes what it was
widened from, so the difference is visible.

exit codes: 1 the HDX call failed, 2 the config has no buffered boundary."""


def as_feature_collection(geometry: dict, properties: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": properties, "geometry": geometry}],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--name", required=True, help="HDX resource name for the geometry")
    parser.add_argument("--category", default=COMBINED_SLUG, help="S3 path segment")
    parser.add_argument(
        "--file-name", help="uploaded filename, default <dataset>_<category>.geojson"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if not cfg.boundary.geom:
        print("error: config has no boundary.geom", file=sys.stderr)
        return 2
    if not cfg.boundary.buffer_meters:
        print(
            "error: config has no boundary.buffer_meters, so this geometry is already "
            "published as the Area of Interest resource",
            file=sys.stderr,
        )
        return 2

    dataset_name = combined_dataset_name(cfg)
    file_name = args.file_name or f"{dataset_name}_{args.category}.geojson"
    geometry = json.loads(cfg.boundary.geom)
    area = area_sq_km(geometry)
    print(f"  {args.name}\n    {file_name}  {area:.2f} sq km")
    if args.dry_run:
        return 0

    bucket, prefix, region, endpoint_url, acl = s3_resolve(cfg.output.s3)
    configure(cfg.hdx.site, cfg.hdx.user_agent)
    collection = as_feature_collection(geometry, {"name": args.name, "area_sq_km": round(area, 2)})
    url = attach_geojson(
        collection,
        dataset_name=dataset_name,
        resource_name=args.name,
        file_name=file_name,
        description=(
            "The geometry the area of interest was built from, before the buffer was applied."
        ),
        key=artifact_key(
            prefix,
            cfg.iso3,
            args.category,
            file_name,
            folder=cfg.output.s3.folder,
            nest_by_category=cfg.output.s3.nest_by_category,
        ),
        bucket=bucket,
        region=region,
        endpoint_url=endpoint_url,
        acl=acl,
    )
    print(f"    -> {url}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HdxPublishError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
