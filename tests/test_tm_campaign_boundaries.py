import sys

import pytest

import tm_campaign_boundaries as tm
from tm_campaign_boundaries import (
    NoProjectsError,
    TaskingManagerError,
    build_collection,
    describe,
    fetch_campaign_projects,
)

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


def page(results, has_next, total=None):
    payload = {"results": results}
    if has_next is not None:
        payload["pagination"] = {"hasNext": has_next, "total": total}
    return payload


def project(project_id, status="PUBLISHED"):
    return {
        "projectId": project_id,
        "status": status,
        "name": f"project {project_id}",
        "percentMapped": 50,
    }


def test_pagination_collects_every_page(monkeypatch):
    pages = [
        page([project(1)], True, 3),
        page([project(2)], True, 3),
        page([project(3)], False, 3),
    ]
    monkeypatch.setattr(tm, "fetch_json", lambda url, timeout: pages.pop(0))
    assert [p["projectId"] for p in fetch_campaign_projects("c", 1, ("PUBLISHED",))] == [1, 2, 3]


def test_a_response_without_pagination_ends_the_walk(monkeypatch):
    """An empty campaign answers with no `pagination` key, which must not loop."""
    calls = []

    def once(url, timeout):
        calls.append(url)
        return page([project(1)], None)

    monkeypatch.setattr(tm, "fetch_json", once)
    assert len(fetch_campaign_projects("c", 1, ("PUBLISHED",))) == 1
    assert len(calls) == 1


def test_a_campaign_that_never_stops_paging_fails(monkeypatch):
    monkeypatch.setattr(tm, "fetch_json", lambda url, timeout: page([project(1)], True))
    with pytest.raises(TaskingManagerError, match="more than"):
        fetch_campaign_projects("c", 1, ("PUBLISHED",))


def test_a_response_without_results_fails(monkeypatch):
    monkeypatch.setattr(tm, "fetch_json", lambda url, timeout: {"pagination": {"hasNext": False}})
    with pytest.raises(TaskingManagerError, match="no `results`"):
        fetch_campaign_projects("c", 1, ("PUBLISHED",))


def test_a_status_the_caller_did_not_ask_for_is_dropped(monkeypatch):
    monkeypatch.setattr(
        tm,
        "fetch_json",
        lambda url, timeout: page([project(1), project(2, "DRAFT")], False),
    )
    assert [p["projectId"] for p in fetch_campaign_projects("c", 1, ("PUBLISHED",))] == [1]


def test_a_project_that_answers_403_is_skipped_not_fatal(monkeypatch):
    """A project made private after the search must not kill the whole campaign."""
    monkeypatch.setattr(tm, "fetch_campaign_projects", lambda *a: [project(1), project(2)])

    def detail(project_id, timeout):
        if project_id == 1:
            raise tm.ProjectForbiddenError("403")
        return {"areaOfInterest": SQUARE}

    monkeypatch.setattr(tm, "fetch_project_detail", detail)
    collection = build_collection("c", 1, ("PUBLISHED",))
    assert [f["properties"]["project_id"] for f in collection["features"]] == [2]


def test_a_campaign_of_only_forbidden_projects_fails_rather_than_publishing_nothing(monkeypatch):
    monkeypatch.setattr(tm, "fetch_campaign_projects", lambda *a: [project(1)])

    def forbidden(project_id, timeout):
        raise tm.ProjectForbiddenError("403")

    monkeypatch.setattr(tm, "fetch_project_detail", forbidden)
    with pytest.raises(NoProjectsError, match="private"):
        build_collection("c", 1, ("PUBLISHED",))


def test_a_short_read_is_refused_rather_than_publishing_a_shrunken_layer(monkeypatch):
    """Overwriting a good HDX resource with a partial one is worse than failing."""
    monkeypatch.setattr(tm, "fetch_json", lambda url, timeout: page([project(1)], False, 9))
    with pytest.raises(TaskingManagerError, match="reported 9 projects but returned 1"):
        fetch_campaign_projects("c", 1, ("PUBLISHED",))


def test_a_response_without_a_total_is_still_accepted(monkeypatch):
    """`total` is not guaranteed, and its absence is not evidence of a short read."""
    monkeypatch.setattr(tm, "fetch_json", lambda url, timeout: page([project(1)], False))
    assert len(fetch_campaign_projects("c", 1, ("PUBLISHED",))) == 1


def test_an_empty_campaign_fails(monkeypatch):
    monkeypatch.setattr(tm, "fetch_campaign_projects", lambda *a: [])
    with pytest.raises(NoProjectsError, match="no projects"):
        build_collection("c", 1, ("PUBLISHED",))


def collection_of(*statuses):
    return {"features": [{"properties": {"status": s}} for s in statuses]}


def test_an_all_archived_campaign_is_not_described_as_live():
    text = describe("c", collection_of("ARCHIVED", "ARCHIVED"))
    assert "percentages are final" in text
    assert "live progress" not in text


def test_a_campaign_with_a_published_project_is_described_as_live():
    text = describe("c", collection_of("ARCHIVED", "PUBLISHED"))
    assert "live progress" in text


def test_a_project_without_a_boundary_fails(monkeypatch):
    monkeypatch.setattr(tm, "fetch_json", lambda url, timeout: {"areaOfInterest": None})
    with pytest.raises(TaskingManagerError, match="no areaOfInterest"):
        tm.fetch_project_detail(7, 1)


def test_the_feature_carries_the_project_link_and_area(monkeypatch):
    feature = tm.build_feature(project(42), {"areaOfInterest": SQUARE}, "camp")
    assert feature["properties"]["project_url"].endswith("/42")
    assert feature["properties"]["area_sq_km"] == pytest.approx(12308.78, abs=0.01)
    assert feature["geometry"] == SQUARE


S3_SETTINGS = ("bucket", "ISO3", "us-east-1", None, "public-read")
ONE_PUBLISHED = {"features": [{"properties": {"status": "PUBLISHED"}}]}


@pytest.fixture
def one_published_project(monkeypatch):
    monkeypatch.setattr(tm, "build_collection", lambda *a: ONE_PUBLISHED)


@pytest.fixture
def published(monkeypatch):
    """The dataset names publish was called with, in order."""
    datasets = []
    monkeypatch.setattr(tm, "publish", lambda *a, **k: datasets.append(k["dataset_name"]))
    return datasets


def run_file(path, dry_run=False):
    return tm.run_campaigns(
        tm.read_campaigns(path),
        timeout=1,
        statuses=("PUBLISHED",),
        s3_settings=None if dry_run else S3_SETTINGS,
    )


def campaigns_file(tmp_path, body):
    path = tmp_path / "campaigns.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_one_failing_campaign_does_not_stop_the_others(tmp_path, monkeypatch, published):
    """A daily run covers every campaign, so a bad one must not cost the rest."""

    def fail_for_bad(campaign, *args):
        if campaign == "bad":
            raise tm.TaskingManagerError("boom")
        return ONE_PUBLISHED

    monkeypatch.setattr(tm, "build_collection", fail_for_bad)
    body = "bad:\n  dataset: d1\n  iso3: NPL\ngood:\n  dataset: d2\n  iso3: NPL\n"
    assert run_file(campaigns_file(tmp_path, body)) == 1
    assert published == ["d2"]


def test_a_failing_publish_is_caught_like_a_failing_fetch(
    tmp_path, monkeypatch, one_published_project
):
    """A failed upload must be reported like a failed fetch, not kill the run."""

    def dataset_not_found(*args, **kwargs):
        raise tm.HdxPublishError("dataset not found")

    monkeypatch.setattr(tm, "publish", dataset_not_found)
    path = campaigns_file(tmp_path, "one:\n  dataset: d1\n  iso3: NPL\n")
    assert run_file(path) == 1


def test_a_disabled_campaign_is_skipped(tmp_path, one_published_project, published):
    body = "off:\n  dataset: d1\n  iso3: NPL\n  enabled: false\non:\n  dataset: d2\n  iso3: NPL\n"
    assert run_file(campaigns_file(tmp_path, body)) == 0
    assert published == ["d2"]


def test_a_campaign_without_a_dataset_fails_only_itself(tmp_path, one_published_project, published):
    """A malformed entry is that campaign's failure; the rest of the file still runs."""
    path = campaigns_file(tmp_path, "bad:\n  iso3: NPL\ngood:\n  dataset: d2\n  iso3: NPL\n")
    assert run_file(path) == 1
    assert published == ["d2"]


def test_a_campaign_without_an_iso3_fails_only_itself(tmp_path, one_published_project, published):
    """Without iso3 the S3 key has no country segment, so the entry must not publish."""
    path = campaigns_file(tmp_path, "bad:\n  dataset: d1\ngood:\n  dataset: d2\n  iso3: NPL\n")
    assert run_file(path) == 1
    assert published == ["d2"]


def test_a_dry_run_publishes_nothing(tmp_path, monkeypatch, one_published_project):
    def fail(*args, **kwargs):
        raise AssertionError("a dry run must not publish")

    monkeypatch.setattr(tm, "publish", fail)
    path = campaigns_file(tmp_path, "one:\n  dataset: d1\n  iso3: NPL\n")
    assert run_file(path, dry_run=True) == 0


def test_every_campaign_succeeding_exits_zero(tmp_path, one_published_project, published):
    """A scheduler reads this exit code to decide whether the run failed."""
    body = "a:\n  dataset: d1\n  iso3: NPL\nb:\n  dataset: d2\n  iso3: NPL\n"
    assert run_file(campaigns_file(tmp_path, body)) == 0


def test_a_campaigns_file_run_needs_no_dataset_on_the_command_line(
    tmp_path, monkeypatch, one_published_project, published
):
    """This is the argv `just tm-boundaries` uses; argparse must accept it."""
    path = campaigns_file(tmp_path, "one:\n  dataset: d1\n  iso3: NPL\n")
    monkeypatch.setattr(sys, "argv", ["tm", "--campaigns-file", str(path)])
    monkeypatch.setattr(tm, "configure_publishing", lambda: S3_SETTINGS)
    assert tm.main() == 0
    assert published == ["d1"]


def test_a_single_campaign_publishes_through_the_same_path(monkeypatch, published):
    """--campaign builds a one-entry mapping, so its flags land where a file entry's would."""
    monkeypatch.setattr(tm, "build_collection", lambda *a: ONE_PUBLISHED)
    argv = ["tm", "--campaign", "c", "--dataset", "d1", "--iso3", "NPL"]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(tm, "configure_publishing", lambda: S3_SETTINGS)
    assert tm.main() == 0
    assert published == ["d1"]


def test_publishing_a_single_campaign_requires_an_iso3(monkeypatch):
    def fail():
        raise AssertionError("argparse must refuse before publishing is configured")

    monkeypatch.setattr(tm, "configure_publishing", fail)
    monkeypatch.setattr(sys, "argv", ["tm", "--campaign", "c", "--dataset", "d1"])
    with pytest.raises(SystemExit) as exit_info:
        tm.main()
    assert exit_info.value.code == 2


def test_writing_to_a_file_needs_no_publishing_settings(tmp_path, monkeypatch):
    """--out is a local export, so it must not load base.yaml or reach HDX."""

    def fail():
        raise AssertionError("--out must not configure publishing")

    monkeypatch.setattr(tm, "build_collection", lambda *a: ONE_PUBLISHED)
    monkeypatch.setattr(tm, "configure_publishing", fail)
    out = tmp_path / "boundaries.geojson"
    monkeypatch.setattr(sys, "argv", ["tm", "--campaign", "c", "--out", str(out)])
    assert tm.main() == 0
    assert out.exists()
