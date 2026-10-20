import pytest

from hdx_resource import HdxPublishError, attach_geojson


def test_an_unset_bucket_fails_before_hdx_is_read(monkeypatch):
    """An empty bucket would otherwise surface as a boto3 error after the dataset lookup."""

    def fail(name):
        raise AssertionError("the dataset must not be read without a bucket")

    monkeypatch.setattr("hdx.data.dataset.Dataset.read_from_hdx", fail)
    with pytest.raises(HdxPublishError, match="bucket"):
        attach_geojson(
            {},
            dataset_name="d",
            resource_name="r",
            file_name="f.geojson",
            description="",
            key="k",
            bucket="",
            region="us-east-1",
            endpoint_url=None,
            acl="public-read",
        )
