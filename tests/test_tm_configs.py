import json
from pathlib import Path
from typing import cast

import pytest
from oex.config.loader import load_config
from oex.config.schema import OsmSourceConfig
from oex.naming import slugify
from omegaconf import OmegaConf
from upath import UPath

import tm_configs

TEMPLATE_PATH = tm_configs.TEMPLATE
TEMPLATE = OmegaConf.create(TEMPLATE_PATH.read_text(encoding="utf-8"))
SEAGRASS_PATH = tm_configs.REPO_ROOT / "configs" / "seagrass_extract.yaml"
GEOM = {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]}
SEAGRASS = {"name": "Seagrass", "tags": ["seamark:type=seagrass"]}


@pytest.fixture
def memory_exports():
    """A dated export prefix on an in-memory filesystem, so no network is involved."""
    root = "memory://tm-exports"
    for day in ("2026-08-04", "2026-08-05", "2026-08-06"):
        UPath(f"{root}/{day}/sandbox-export.pbf").write_bytes(b"PBFDATA")
    return root


def feature(project_id, mapping_types, geom=None, custom=None):
    return {
        "geometry": geom or GEOM,
        "properties": {
            "project_id": project_id,
            "mapping_types": mapping_types,
            "custom_mapping_types": custom,
        },
    }


def build(project_id=4242, mapping_types=(2,), custom=None):
    return tm_configs.build_config(
        TEMPLATE, feature(project_id, list(mapping_types), custom=custom)
    )


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


def test_a_key_alone_matches_any_value():
    [category] = tm_configs.custom_categories(
        [{"name": "Water", "tags": ["waterway=*", "amenity=drinking_water", "amenity=*"]}]
    )
    assert category["osm"]["filter"] == {"waterway": True, "amenity": True}


def test_custom_columns_never_repeat_and_id_stays_the_feature_id():
    attributes = ["id", "name", "addr:street", "addr_street"]
    [category] = tm_configs.custom_categories(
        [{"name": "Wells", "tags": ["man_made=water_well"], "attributes": attributes}]
    )
    assert category["osm"]["select"] == [
        "feature_id AS id",
        "tags['name'] AS name",
        "tags['man_made'] AS man_made",
        "tags['addr:street'] AS addr_street",
        "tags['source'] AS source",
    ]


def test_custom_columns_run_in_duckdb():
    import duckdb
    from oex.sql import build_select_clause

    [category] = tm_configs.custom_categories(
        [{"name": "Tracks", "tags": ["4wd_only=yes", ":=x", "geom=x", "natural=*"]}]
    )
    con = duckdb.connect()
    con.execute("CREATE TABLE src AS SELECT 1 AS feature_id, MAP {'k': 'v'} AS tags, 1 AS geometry")
    con.execute(
        f"CREATE TABLE t AS SELECT {build_select_clause(category['osm']['select'])} FROM src"
    )
    columns = [row[0] for row in con.execute("DESCRIBE t").fetchall()]
    assert columns == ["id", "name", "4wd_only", "natural", "source", "geom"]


@pytest.mark.parametrize(
    "custom",
    [
        {"name": "Buildings", "tags": ["building=yes"]},
        {"name": "", "tags": ["building=yes"]},
        {"name": "${oc.env:AWS_SECRET_ACCESS_KEY}", "tags": ["building=yes"]},
        {"name": "Wells", "tags": []},
        {"name": "Wells", "tags": ["man_made"]},
        {"name": "Wells", "tags": ["man_made="]},
        {"name": "Wells", "tags": ["man'made=water_well"]},
        {"name": "Wells", "tags": ["man_made=${oc.env:AWS_SECRET_ACCESS_KEY}"]},
        {"name": "Wells", "tags": ["man_made=water_well"], "attributes": ["x') AS y --"]},
        {"name": "Wells", "tags": "man_made=water_well"},
        {"name": "Wells", "tags": ["man_made=water_well"], "attributes": "name"},
        "Wells",
        None,
    ],
)
def test_a_custom_type_that_breaks_the_tm_validation_is_skipped(custom):
    assert tm_configs.custom_categories([custom]) == []


@pytest.mark.parametrize("custom_types", ['[{"name": "Wells"}]', {"name": "Wells"}, 5])
def test_custom_types_that_are_not_a_list_are_ignored(custom_types):
    assert tm_configs.custom_categories(custom_types) == []


def test_two_custom_types_cannot_share_a_folder():
    customs = [SEAGRASS, {**SEAGRASS, "name": "seagrass"}]
    assert [c["name"] for c in tm_configs.custom_categories(customs)] == ["Seagrass"]


def test_custom_types_are_added_to_the_mapping_type_categories():
    cfg = build(mapping_types=(2,), custom=[SEAGRASS])
    assert [c.name for c in cfg.categories] == ["Buildings", "Seagrass"]


def test_a_project_with_only_custom_types_is_generated(tmp_path, monkeypatch):
    """Mapping type 5 is OTHER, which no template category covers."""
    monkeypatch.setattr("sys.argv", ["tm_configs", "--out", str(tmp_path)])
    monkeypatch.setattr(
        tm_configs, "fetch_active_projects", lambda *_: [feature(1, [5], custom=[SEAGRASS])]
    )
    assert tm_configs.main() == 0
    assert [c.name for c in OmegaConf.load(tmp_path / "1.yaml").categories] == ["Seagrass"]


def test_a_caller_supplied_template_ignores_custom_types():
    cfg = tm_configs.build_config(TEMPLATE, feature(1, [2], custom=[SEAGRASS]), None, True)
    assert "Seagrass" not in [c.name for c in cfg.categories]


def test_a_custom_type_lands_in_the_folder_the_tm_frontend_requests():
    """The frontend lowercases the name and joins its words with `_`, as oex does."""
    cfg = build(custom=[{"name": "Water points", "tags": ["amenity=drinking_water"]}])
    assert slugify(cfg.categories[-1].name) == "water_points"


def test_a_custom_type_loads_as_an_oex_category(tmp_path, monkeypatch):
    monkeypatch.setenv("OEX_S3_BUCKET", "bucket")
    tm_configs.sync(tmp_path, {"1.yaml": build(1, custom=[SEAGRASS])}, dry_run=False)
    cfg = load_config(tmp_path / "1.yaml")
    assert [c.name for c in cfg.categories] == ["Buildings", "Seagrass"]
    assert cfg.categories[-1].osm.filter == {"seamark:type": ["seagrass"]}


def pbf_path(cfg) -> str:
    """Unresolved, so the assertion does not depend on the environment."""
    container = cast(dict, OmegaConf.to_container(cfg, resolve=False))
    return container["source"]["osm"]["pbf_path"]


def test_the_seagrass_template_reads_the_planet_the_countries_read():
    assert pbf_path(OmegaConf.load(SEAGRASS_PATH)) == pbf_path(
        OmegaConf.load(tm_configs.REPO_ROOT / "configs" / "base.yaml")
    )


def test_a_config_without_an_extract_keeps_the_template_live_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("OEX_S3_BUCKET", "exports")
    path = tmp_path / "4242.yaml"
    path.write_text(OmegaConf.to_yaml(build(), resolve=False), encoding="utf-8")
    osm = cast(OsmSourceConfig, load_config(path).source["osm"])
    assert (osm.engine, osm.fallback_engine) == ("postpass", "rawdata")
    assert osm.postpass_max_area_sq_km == 5000


def test_sandbox_configs_need_extract(tmp_path, monkeypatch, capsys):
    """Without it a sandbox config would point at the folder of daily exports."""
    monkeypatch.setattr("sys.argv", ["tm_configs", "--sandbox", "--out", str(tmp_path)])
    assert tm_configs.main() == 2
    assert "--sandbox needs --extract" in capsys.readouterr().err


def test_a_project_without_its_own_extract_reads_the_resolved_source(tmp_path, monkeypatch):
    """The sandbox variable is a folder, so the fallback must be the day's downloaded file."""
    source = tmp_path / "2026-11-10-sandbox-export.pbf"
    monkeypatch.setattr(
        "sys.argv", ["tm_configs", "--sandbox", "--extract", "--out", str(tmp_path)]
    )
    monkeypatch.setenv(tm_configs.SANDBOX_PBF_ENV, "s3://sandbox/exports/")
    monkeypatch.setattr(tm_configs, "fetch_active_projects", lambda *_: [feature(1, [2])])
    monkeypatch.setattr(tm_configs, "cut_project_extracts", lambda *_: ({}, source))
    assert tm_configs.main() == 0
    written = OmegaConf.load(tmp_path / "1.yaml")
    assert written.source.osm.pbf_path == str(source)


def test_the_template_is_never_mutated_between_projects():
    before = OmegaConf.to_yaml(TEMPLATE, resolve=False)
    build(mapping_types=(2,))
    assert OmegaConf.to_yaml(TEMPLATE, resolve=False) == before


def test_an_interval_beyond_the_api_cap_is_rejected():
    with pytest.raises(tm_configs.TaskingManagerError, match="interval"):
        tm_configs.fetch_active_projects(48, sandbox=False, timeout=1)


def test_sync_writes_new_configs(tmp_path):
    assert tm_configs.sync(tmp_path, {"1.yaml": build(1)}, dry_run=False) == 1
    assert (tmp_path / "1.yaml").exists()


def test_sync_leaves_unchanged_configs_alone(tmp_path):
    configs = {"1.yaml": build(1)}
    tm_configs.sync(tmp_path, configs, dry_run=False)
    assert tm_configs.sync(tmp_path, configs, dry_run=False) == 0


def test_a_config_missing_from_the_api_is_kept(tmp_path):
    """The API reports what moved in the interval, so its silence is not a delete signal."""
    tm_configs.sync(tmp_path, {"1.yaml": build(1), "2.yaml": build(2)}, dry_run=False)
    assert tm_configs.sync(tmp_path, {"1.yaml": build(1)}, dry_run=False) == 0
    assert (tmp_path / "2.yaml").exists()
    assert (tmp_path / "1.yaml").exists()


def test_dry_run_touches_nothing(tmp_path):
    (tmp_path / "9.yaml").write_text("stale", encoding="utf-8")
    assert tm_configs.sync(tmp_path, {"1.yaml": build(1)}, dry_run=True) == 1
    assert not (tmp_path / "1.yaml").exists()
    assert (tmp_path / "9.yaml").read_text(encoding="utf-8") == "stale"


def test_a_config_on_its_own_extract_reads_it_and_never_downloads_the_planet(tmp_path):
    """A kept extract falls behind the published planet, so oex would download over it."""
    cfg = tm_configs.build_config(TEMPLATE, feature(7, [2]), tmp_path / "7.osm.pbf")
    assert pbf_path(cfg) == str(tmp_path / "7.osm.pbf")
    assert cfg.source.osm.auto_download_planet is False
    assert (cfg.source.osm.engine, cfg.source.osm.fallback_engine) == ("planet", "")


@pytest.fixture
def planet_refreshes(monkeypatch, tmp_path):
    """Records each planet refresh instead of downloading the planet."""
    monkeypatch.setenv("OEX_S3_BUCKET", "exports")
    monkeypatch.setenv("OEX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(tm_configs.SANDBOX_PBF_ENV, "s3://sandbox/exports/")
    calls = []
    monkeypatch.setattr(tm_configs, "refresh_planet_pbf", lambda _osm, path: calls.append(path))
    return calls


def test_a_planet_template_extracts_from_the_refreshed_planet(tmp_path, planet_refreshes):
    """Sandbox exports lack production edits, so a set sandbox variable must not leak in."""
    planet = str(tmp_path / "data/osm/planet/planet-latest.osm.pbf")
    assert tm_configs.extract_source(SEAGRASS_PATH, sandbox=False) == planet
    assert planet_refreshes == [Path(planet)]


@pytest.mark.parametrize(
    ("setting", "replacement"),
    [
        ("engine: planet", "engine: postpass"),
        ("auto_download_planet: true", "auto_download_planet: false"),
        ("pbf_path: ${oc.env:OEX_DATA_DIR,.}", "pbf_path: s3://bucket"),
    ],
)
def test_the_planet_is_left_alone_unless_the_template_refreshes_a_local_one(
    tmp_path, planet_refreshes, setting, replacement
):
    """A remote source is copied from its own location, never from planet.openstreetmap.org."""
    text = SEAGRASS_PATH.read_text(encoding="utf-8")
    assert setting in text
    template = tmp_path / "template.yaml"
    template.write_text(text.replace(setting, replacement, 1), encoding="utf-8")
    tm_configs.extract_source(template, sandbox=False)
    assert planet_refreshes == []


def test_sandbox_projects_extract_from_the_sandbox_exports(planet_refreshes):
    assert tm_configs.extract_source(TEMPLATE_PATH, sandbox=True) == "s3://sandbox/exports/"
    assert planet_refreshes == []


def test_sandbox_extracts_need_the_sandbox_exports_set(monkeypatch):
    """The planet does not hold sandbox edits, so there is nothing to fall back to."""
    monkeypatch.delenv(tm_configs.SANDBOX_PBF_ENV, raising=False)
    with pytest.raises(tm_configs.TaskingManagerError, match=tm_configs.SANDBOX_PBF_ENV):
        tm_configs.extract_source(TEMPLATE_PATH, sandbox=True)


def test_the_osmium_config_holds_one_extract_per_project(tmp_path):
    features = [feature(1, [2]), feature(2, [1])]
    config, outputs = tm_configs.write_osmium_config(features, tmp_path)
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["directory"] == str(tmp_path)
    assert [e["output"] for e in written["extracts"]] == ["1.osm.pbf", "2.osm.pbf"]
    assert set(outputs) == {"1", "2"}


def test_each_extract_gets_its_own_polygon_file(tmp_path):
    tm_configs.write_osmium_config([feature(1, [2])], tmp_path)
    written = json.loads((tmp_path / "1.geojson").read_text(encoding="utf-8"))
    assert written == {"type": "Feature", "properties": {}, "geometry": GEOM}


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


def test_extract_rejects_a_source_that_is_not_there(tmp_path):
    with pytest.raises(tm_configs.TaskingManagerError, match="is not a file"):
        tm_configs.cut_project_extracts(
            [feature(1, [2])], str(tmp_path / "absent.osm.pbf"), tmp_path
        )


@pytest.mark.parametrize(("count", "sizes"), [(13, [6, 6, 1]), (6, [6]), (1, [1])])
def test_projects_are_split_into_batches_of_at_most_the_size(count, sizes):
    features = [feature(index, [2]) for index in range(count)]
    assert [len(batch) for batch in tm_configs.batches(features, 6)] == sizes


def test_each_osmium_pass_cuts_one_batch_and_every_project_gets_its_extract(tmp_path, monkeypatch):
    source = tmp_path / "source.osm.pbf"
    source.write_bytes(b"pbf")
    passes = []

    def record_pass(_source, config):
        extracts = json.loads(config.read_text(encoding="utf-8"))["extracts"]
        passes.append([extract["output"] for extract in extracts])
        for name in passes[-1]:
            (tmp_path / name).write_bytes(b"pbf")

    monkeypatch.setenv(tm_configs.EXTRACT_BATCH_ENV, "2")
    monkeypatch.setattr(tm_configs, "run_osmium_extract", record_pass)
    monkeypatch.setattr(tm_configs, "node_count", lambda _pbf: 1)
    usable, _ = tm_configs.cut_project_extracts(
        [feature(index, [2]) for index in range(5)], str(source), tmp_path
    )
    assert passes == [["0.osm.pbf", "1.osm.pbf"], ["2.osm.pbf", "3.osm.pbf"], ["4.osm.pbf"]]
    assert sorted(usable) == ["0", "1", "2", "3", "4"]


@pytest.mark.parametrize("value", ["0", "six", "-2"])
def test_a_batch_size_that_is_not_a_positive_whole_number_is_rejected(monkeypatch, value):
    monkeypatch.setenv(tm_configs.EXTRACT_BATCH_ENV, value)
    with pytest.raises(tm_configs.TaskingManagerError, match=tm_configs.EXTRACT_BATCH_ENV):
        tm_configs.extract_batch_size()
