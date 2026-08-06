import json

import pytest
import tm_configs
from omegaconf import OmegaConf
from upath import UPath

TEMPLATE = OmegaConf.create(tm_configs.TEMPLATE.read_text(encoding="utf-8"))
GEOM = {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]}


@pytest.fixture
def memory_exports():
    """A dated export prefix on an in-memory filesystem, so no network is involved."""
    root = "memory://tm-exports"
    for day in ("2026-08-04", "2026-08-05", "2026-08-06"):
        UPath(f"{root}/{day}/sandbox-export.pbf").write_bytes(b"PBFDATA")
    return root


def feature(project_id, mapping_types, geom=None):
    return {
        "geometry": geom or GEOM,
        "properties": {"project_id": project_id, "mapping_types": mapping_types},
    }


def build(project_id=4242, mapping_types=(2,), sandbox=False):
    return tm_configs.build_config(TEMPLATE, feature(project_id, list(mapping_types)), sandbox)


def test_mapping_type_ints_are_one_based_indexes():
    assert tm_configs.category_names([1, 2, 3, 4]) == ["Roads", "Buildings", "Waterways", "Landuse"]


def test_mapping_type_strings_are_accepted():
    assert tm_configs.category_names(["BUILDINGS", "LAND_USE"]) == ["Buildings", "Landuse"]


def test_unsupported_mapping_types_are_dropped():
    assert tm_configs.category_names([9, 0, "SATELLITE_IMAGERY", None]) == []


def test_missing_mapping_types_are_dropped():
    assert tm_configs.category_names(None) == []


def test_a_project_identifies_by_id_and_carries_no_country():
    """The folder is the whole dataset prefix, which the TM frontend uses as the path."""
    cfg = build(project_id=4242)
    assert cfg.output.s3.folder == "hotosm_project_4242"
    assert "iso3" not in cfg
    assert cfg.dataset_name == "Tasking Manager Project 4242"


def test_the_generated_config_produces_the_key_the_tm_frontend_requests():
    from oex.s3 import artifact_key

    cfg = build(project_id=4242)
    s3 = cfg.output.s3
    key = artifact_key(
        s3.prefix,
        "",
        "buildings",
        "hotosm_project_4242_buildings_polygons_shp.zip",
        folder=s3.folder,
        nest_by_category=s3.nest_by_category,
        geometry="polygons" if s3.nest_by_geometry else "",
    )
    assert key == (
        "TM/hotosm_project_4242/buildings/polygons/hotosm_project_4242_buildings_polygons_shp.zip"
    )


def test_the_project_polygon_becomes_the_boundary():
    cfg = build()
    assert json.loads(cfg.boundary.geom) == GEOM


def test_categories_are_trimmed_to_the_project_mapping_types():
    cfg = build(mapping_types=(2, 1))
    assert sorted(c.name for c in cfg.categories) == ["Buildings", "Roads"]


def test_a_project_with_no_supported_mapping_type_is_not_generated():
    assert build(mapping_types=()) is None
    assert build(mapping_types=(99,)) is None


def pbf_path(cfg):
    """Unresolved, so the assertion does not depend on the environment."""
    return OmegaConf.to_container(cfg, resolve=False)["source"]["osm"]["pbf_path"]


def test_production_reads_the_planet_pbf_from_the_environment():
    assert pbf_path(build()) == "${oc.env:TM_PBF}"


def test_sandbox_reads_its_own_pbf_from_the_environment():
    assert pbf_path(build(sandbox=True)) == "${oc.env:TM_SANDBOX_PBF}"


def test_the_template_is_never_mutated_between_projects():
    before = OmegaConf.to_yaml(TEMPLATE, resolve=False)
    build(mapping_types=(2,))
    assert OmegaConf.to_yaml(TEMPLATE, resolve=False) == before


def test_an_interval_beyond_the_api_cap_is_rejected():
    with pytest.raises(tm_configs.TaskingManagerError, match="interval"):
        tm_configs.fetch_active_projects(48, sandbox=False, timeout=1)


def test_sync_writes_new_configs(tmp_path):
    written, pruned = tm_configs.sync(tmp_path, {"1.yaml": build(1)}, dry_run=False)
    assert (written, pruned) == (1, 0)
    assert (tmp_path / "1.yaml").exists()


def test_sync_leaves_unchanged_configs_alone(tmp_path):
    configs = {"1.yaml": build(1)}
    tm_configs.sync(tmp_path, configs, dry_run=False)
    written, pruned = tm_configs.sync(tmp_path, configs, dry_run=False)
    assert (written, pruned) == (0, 0)


def test_sync_prunes_projects_that_are_no_longer_active(tmp_path):
    tm_configs.sync(tmp_path, {"1.yaml": build(1), "2.yaml": build(2)}, dry_run=False)
    written, pruned = tm_configs.sync(tmp_path, {"1.yaml": build(1)}, dry_run=False)
    assert pruned == 1
    assert not (tmp_path / "2.yaml").exists()
    assert (tmp_path / "1.yaml").exists()


def test_dry_run_touches_nothing(tmp_path):
    (tmp_path / "9.yaml").write_text("stale", encoding="utf-8")
    written, pruned = tm_configs.sync(tmp_path, {"1.yaml": build(1)}, dry_run=True)
    assert (written, pruned) == (1, 1)
    assert not (tmp_path / "1.yaml").exists()
    assert (tmp_path / "9.yaml").read_text(encoding="utf-8") == "stale"


def test_a_per_project_pbf_overrides_the_environment_default(tmp_path):
    cfg = tm_configs.build_config(TEMPLATE, feature(7, [2]), False, tmp_path / "7.osm.pbf")
    assert pbf_path(cfg) == str(tmp_path / "7.osm.pbf")


def test_the_osmium_config_holds_one_extract_per_project(tmp_path):
    features = [feature(1, [2]), feature(2, [1])]
    config, outputs = tm_configs.write_osmium_config(features, tmp_path)
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["directory"] == str(tmp_path)
    assert [e["output"] for e in written["extracts"]] == ["1.osm.pbf", "2.osm.pbf"]
    assert set(outputs) == {"1", "2"}


def test_each_extract_gets_its_own_polygon_file(tmp_path):
    tm_configs.write_osmium_config([feature(1, [2])], tmp_path)
    assert json.loads((tmp_path / "1.geojson").read_text(encoding="utf-8")) == GEOM


def test_extract_needs_the_source_pbf_in_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv(tm_configs.PBF_ENV, raising=False)
    with pytest.raises(tm_configs.TaskingManagerError, match=tm_configs.PBF_ENV):
        tm_configs.cut_project_extracts([feature(1, [2])], sandbox=False, pbf_dir=tmp_path)


def test_a_plain_location_is_used_as_is():
    assert tm_configs.resolve_source_pbf("/data/planet.osm.pbf") == "/data/planet.osm.pbf"


def test_a_prefix_resolves_to_the_newest_dated_export(memory_exports):
    resolved = tm_configs.resolve_source_pbf(f"{memory_exports}/")
    assert resolved.endswith("2026-08-06/sandbox-export.pbf")


def test_a_prefix_with_no_dated_folders_is_an_error():
    UPath("memory://empty/readme.txt").write_text("no dates here")
    with pytest.raises(tm_configs.TaskingManagerError, match="YYYY-MM-DD"):
        tm_configs.resolve_source_pbf("memory://empty/")


def test_a_dated_folder_with_no_pbf_is_an_error():
    UPath("memory://nopbf/2026-08-06/notes.txt").write_text("nothing to extract")
    with pytest.raises(tm_configs.TaskingManagerError, match="no .pbf"):
        tm_configs.resolve_source_pbf("memory://nopbf/")


def test_a_local_source_is_not_copied(tmp_path):
    local = tmp_path / "planet.osm.pbf"
    local.write_bytes(b"pbf")
    assert tm_configs.ensure_local_pbf(str(local), tmp_path / "cache") == local


def test_a_remote_source_is_downloaded_once_and_then_reused(tmp_path, memory_exports, capsys):
    remote = f"{memory_exports}/2026-08-06/sandbox-export.pbf"
    first = tm_configs.ensure_local_pbf(remote, tmp_path)
    assert first.read_bytes() == b"PBFDATA"
    capsys.readouterr()
    second = tm_configs.ensure_local_pbf(remote, tmp_path)
    assert second == first
    assert "reusing" in capsys.readouterr().out


def test_extract_rejects_a_source_that_is_not_there(tmp_path, monkeypatch):
    monkeypatch.setenv(tm_configs.PBF_ENV, str(tmp_path / "absent.osm.pbf"))
    with pytest.raises(tm_configs.TaskingManagerError, match="is not a file"):
        tm_configs.cut_project_extracts([feature(1, [2])], sandbox=False, pbf_dir=tmp_path)


def test_sandbox_extract_reads_its_own_source_variable(tmp_path, monkeypatch):
    monkeypatch.delenv(tm_configs.SANDBOX_PBF_ENV, raising=False)
    with pytest.raises(tm_configs.TaskingManagerError, match=tm_configs.SANDBOX_PBF_ENV):
        tm_configs.cut_project_extracts([feature(1, [2])], sandbox=True, pbf_dir=tmp_path)
