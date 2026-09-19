"""Tests for bounded parameter-driven series baking (particles, dynamics, animation)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import graph_authoring as api
from dcc_mcp_substance3d_designer import graph_series as series

_UID = "graph-A"


def test_numeric_values_builds_bounded_even_sweep():
    assert series.numeric_values(0, 1, 5, "float") == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert series.numeric_values(0, 4, 3, "int") == [0, 2, 4]
    assert series.numeric_values(7, 99, 1, "float") == [7.0]


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"start": 0, "stop": 1, "count": 0, "value_type": "float"}, "INVALID_SERIES_COUNT"),
        ({"start": 0, "stop": 1, "count": 65, "value_type": "float"}, "INVALID_SERIES_COUNT"),
        ({"start": 0, "stop": 1, "count": 2, "value_type": "texture"}, "UNSUPPORTED_VALUE_TYPE"),
        ({"start": float("nan"), "stop": 1, "count": 2, "value_type": "float"}, "INVALID_SERIES_RANGE"),
        ({"start": 0, "stop": 2e9, "count": 2, "value_type": "float"}, "INVALID_SERIES_RANGE"),
    ],
)
def test_numeric_values_rejects_unsupported_requests(kwargs, code):
    with pytest.raises(api.GraphAuthoringError) as error:
        series.numeric_values(**kwargs)
    assert error.value.code == code


@pytest.mark.parametrize(
    "values, code",
    [
        ([], "INVALID_SERIES_VALUES"),
        ([1] * 65, "INVALID_SERIES_VALUES"),
        ([float("inf")], "INVALID_SERIES_VALUES"),
        ([True], "INVALID_SERIES_VALUES"),
        ([2e9], "INVALID_SERIES_VALUES"),
        ("not-a-list", "INVALID_SERIES_VALUES"),
    ],
)
def test_require_values_rejects_unbounded_input(values, code):
    with pytest.raises(api.GraphAuthoringError) as error:
        series.require_values(values)
    assert error.value.code == code


@pytest.mark.parametrize("prefix", ["frame", "ok", "ok"])
def test_prefix_must_be_a_graph_safe_identifier(prefix):
    assert series.require_prefix(prefix) == prefix


@pytest.mark.parametrize("prefix", ["", "1st", "has-dash", "../escape"])
def test_prefix_rejects_unsafe_names(prefix):
    with pytest.raises(api.GraphAuthoringError) as error:
        series.require_prefix(prefix)
    assert error.value.code == "INVALID_SERIES_PREFIX"


@pytest.mark.parametrize("resolution", [128, 3072, 8192, "2048"])
def test_resolution_budget_is_allowlisted(resolution):
    with pytest.raises(api.GraphAuthoringError) as error:
        series.require_resolution(resolution)
    assert error.value.code == "INVALID_RESOLUTION_BUDGET"


@pytest.fixture
def series_graph(monkeypatch, tmp_path):
    """Graph double that records the parameter values a sweep writes."""
    state = {"writes": [], "value": 0.0, "exports": []}

    graph = SimpleNamespace(
        getUID=lambda: _UID,
        getNodes=lambda: [],
        getProperties=lambda category: [],
    )
    monkeypatch.setattr(api, "active_graph", lambda: graph)

    def fake_set_parameter(node_id, parameter, value_type, value, expected_graph_uid=None):
        state["writes"].append(value)
        state["value"] = value
        return {"node_id": node_id, "parameter": parameter, "value": value}

    def fake_get_parameter(node_id, parameter):
        return {"node_id": node_id, "parameter": parameter, "value": 0.0}

    def fake_export(output_dir, outputs, expected_graph_uid, max_resolution):
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        files = []
        for item in outputs:
            path = destination / f"{item['name']}.png"
            path.write_bytes(b"texture-bytes")
            files.append({"name": item["name"], "path": str(path), "node_id": item["node_id"]})
        state["exports"].append(str(destination))
        return {
            "graph_uid": expected_graph_uid,
            "files": files,
            "precision_policy": "native SDK texture precision",
        }

    monkeypatch.setattr(api, "set_parameter", fake_set_parameter)
    monkeypatch.setattr(api, "get_parameter", fake_get_parameter)
    monkeypatch.setattr(series, "export_native_maps", fake_export)
    monkeypatch.setitem(sys.modules, "sd", ModuleType("sd"))
    return state


_OUTPUTS = [{"name": "height", "node_id": "100", "property": "output"}]


def test_bake_series_writes_every_value_and_exports_each_step(series_graph, tmp_path):
    target = tmp_path / "series"
    result = series.bake_variation_series(str(target), "100", "seed", "int", 1, 4, 4, _OUTPUTS, _UID, 1024)
    assert result["step_count"] == 4
    assert series_graph["writes"] == [1, 2, 3, 4]
    assert [step["index"] for step in result["steps"]] == [0, 1, 2, 3]
    assert all(Path(step["output_dir"]).name == f"tile_{index:04d}" for index, step in enumerate(result["steps"]))
    assert all(Path(file["path"]).is_file() for step in result["steps"] for file in step["files"])
    assert result["series_kind"] == "variation"


def test_bake_series_refuses_an_existing_output_directory(series_graph, tmp_path):
    existing = tmp_path / "already"
    existing.mkdir()
    with pytest.raises(api.GraphAuthoringError) as error:
        series.bake_animation_frames(str(existing), "100", "time", "float", 0, 1, 3, _OUTPUTS, _UID)
    assert error.value.code == "OUTPUT_EXISTS"
    assert series_graph["writes"] == []


def test_bake_series_restores_the_parameter_when_a_step_fails(series_graph, tmp_path, monkeypatch):
    """A failing step must restore the swept parameter to its original value."""

    def always_fail(output_dir, outputs, expected_graph_uid, max_resolution):
        raise api.GraphAuthoringError("export failed", "MAP_OUTPUT_MISSING")

    monkeypatch.setattr(series, "export_native_maps", always_fail)
    with pytest.raises(api.GraphAuthoringError) as error:
        series.bake_iteration_series(str(tmp_path / "passes"), "100", "iterations", 0, 4, 4, _OUTPUTS, _UID)
    assert error.value.code == "MAP_OUTPUT_MISSING"
    # The sweep wrote 0 (first value), then rolled back to the original 0.0.
    assert series_graph["value"] == 0.0
    assert series_graph["writes"][-1] == 0.0


def test_series_families_are_labeled_by_kind(series_graph, tmp_path):
    variation = series.bake_variation_series(str(tmp_path / "v"), "100", "seed", "float", 0, 1, 2, _OUTPUTS, _UID)
    passes = series.bake_iteration_series(str(tmp_path / "d"), "100", "iter", 0, 2, 3, _OUTPUTS, _UID)
    frames = series.bake_animation_frames(str(tmp_path / "a"), "100", "time", "float", 0, 1, 2, _OUTPUTS, _UID)
    assert variation["series_kind"] == "variation"
    assert passes["series_kind"] == "iteration"
    assert frames["series_kind"] == "animation"
    assert "solver" in passes["series_note"]
    assert "timeline" in frames["series_note"]


def test_iteration_series_coerces_values_to_integers(series_graph, tmp_path):
    result = series.bake_iteration_series(str(tmp_path / "i"), "100", "iterations", 0, 1, 3, _OUTPUTS, _UID)
    assert result["values"] == [0, 1, 1] or result["values"] == [0, 0, 1]
    assert all(isinstance(value, int) for value in result["values"])


def test_compose_atlas_requires_qt_gui(monkeypatch, tmp_path):
    """Without PySide2 QtGui the atlas path fails closed instead of silently skipping."""
    series_dir = tmp_path / "series"
    (series_dir / "tile_0000").mkdir(parents=True)
    (series_dir / "tile_0000" / "height.png").write_bytes(b"x")
    monkeypatch.setitem(sys.modules, "PySide2.QtGui", None)
    with pytest.raises(api.GraphAuthoringError) as error:
        series.compose_atlas(str(series_dir), str(tmp_path / "atlas.png"), "height.png")
    assert error.value.code == "ATLAS_COMPOSER_UNAVAILABLE"


def test_compose_atlas_rejects_unsafe_file_names(tmp_path):
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    with pytest.raises(api.GraphAuthoringError) as error:
        series.compose_atlas(str(series_dir), str(tmp_path / "a.png"), "../escape.png")
    assert error.value.code == "INVALID_ATLAS_FILE"


def test_compose_atlas_rejects_a_missing_series_directory(tmp_path):
    with pytest.raises(api.GraphAuthoringError) as error:
        series.compose_atlas(str(tmp_path / "nope"), str(tmp_path / "a.png"), "height.png")
    assert error.value.code == "SERIES_DIR_NOT_FOUND"


def test_bake_series_reports_that_the_parameter_is_not_restored_on_success(series_graph, tmp_path):
    """Finding #5: success must not claim the graph was restored."""
    result = series.bake_animation_frames(str(tmp_path / "frames"), "100", "time", "float", 0, 1, 3, _OUTPUTS, _UID)
    assert result["parameter_restored"] is False
    assert result["original_value"] == 0.0
    assert result["final_value"] == 1.0
    assert result["values"] == [0.0, 0.5, 1.0]


def test_list_animation_parameters_reports_the_real_scanned_count(monkeypatch):
    """Finding #4: scanned_nodes must be the graph's node count, not the cap."""
    node = SimpleNamespace(
        getIdentifier=lambda: "100",
        getProperties=lambda category: [],
        getPropertyValue=lambda prop: None,
        getPropertyConnections=lambda prop: [],
    )
    graph = SimpleNamespace(
        getUID=lambda: _UID,
        getNodes=lambda: [node] * 5,
        getProperties=lambda category: [],
    )
    monkeypatch.setattr(api, "active_graph", lambda: graph)
    monkeypatch.setattr(api, "node_identifier", lambda node: "100")
    monkeypatch.setattr(api, "json_value", lambda value: value)
    monkeypatch.setitem(sys.modules, "sd", ModuleType("sd"))
    monkeypatch.setitem(sys.modules, "sd.api", ModuleType("sd.api"))
    property_module = ModuleType("sd.api.sdproperty")
    property_module.SDPropertyCategory = SimpleNamespace(Input="Input", Output="Output")
    monkeypatch.setitem(sys.modules, "sd.api.sdproperty", property_module)

    result = series.list_animation_parameters(_UID, scan_nodes=True, max_nodes=200)
    # 5 nodes in the graph, so it reports 5 rather than the 200 cap.
    assert result["scanned_nodes"] == 5
    assert result["scan_limit"] == 200
    assert result["scan_truncated"] is False
