"""Attach a GeoJSON payload to an HDX dataset as one S3-hosted resource."""

import json
import os
import tempfile
from pathlib import Path


class HdxPublishError(Exception):
    """The dataset could not be found or updated."""


def _required_env(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError as error:
        raise HdxPublishError(f"{name} is not set") from error


def configure(site: str, user_agent: str) -> None:
    """Once per process: hdx-python-api refuses a second Configuration.create."""
    from hdx.api.configuration import Configuration

    Configuration.create(hdx_site=site, hdx_key=_required_env("HDX_API_KEY"), user_agent=user_agent)


def attach_geojson(
    collection: dict,
    *,
    dataset_name: str,
    resource_name: str,
    file_name: str,
    description: str,
    key: str,
    bucket: str,
    region: str,
    endpoint_url: str | None,
    acl: str,
) -> str:
    """The dataset is read first so a wrong name fails before anything is uploaded."""
    from hdx.data.dataset import Dataset
    from hdx.data.resource import Resource
    from oex.s3 import upload as s3_upload

    if not bucket:
        raise HdxPublishError("no S3 bucket is configured")
    dataset = Dataset.read_from_hdx(dataset_name)
    if dataset is None:
        raise HdxPublishError(f"HDX dataset {dataset_name} not found")

    with tempfile.TemporaryDirectory() as work_dir:
        payload_path = Path(work_dir) / file_name
        payload_path.write_text(
            json.dumps(collection, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        url = s3_upload(
            payload_path,
            bucket=bucket,
            key=key,
            region=region,
            endpoint_url=endpoint_url,
            acl=acl,
        )
        resource = Resource(
            {
                "name": resource_name,
                "description": description,
                "format": "geojson",
                "size": payload_path.stat().st_size,
                "url": url,
            }
        )
        resource.mark_data_updated()
        dataset.add_update_resource(resource)
        dataset.update_in_hdx(
            match_resources_by_metadata=True,
            hxl_update=False,
            remove_additional_resources=False,
        )
    return url
