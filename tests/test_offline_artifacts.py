"""No stale artifact or metadata-only PNG can prove a native CLI export."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from dcc_mcp_substance3d_designer import offline_artifacts as offline
from dcc_mcp_substance3d_designer.graph_authoring import GraphAuthoringError


def _png(depth=8, value=0):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    row = b"\0" + bytes([value]) * (256 * depth // 8)
    header = struct.pack(">IIBBBBB", 256, 256, depth, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(row * 256)) + chunk(b"IEND", b"")
    )


@pytest.fixture
def render_request(tmp_path, monkeypatch):
    executable = tmp_path / "sbsrender"
    executable.write_bytes(b"test-only fake native runner identity")
    engine = tmp_path / "plugins/engines/substance_sse2_blend.dll"
    engine.parent.mkdir(parents=True)
    engine.write_bytes(b"test-only fixed native engine identity")
    archive = tmp_path / "input.sbsar"
    archive.write_bytes(b"test-only archive; native baking is a separate smoke")
    monkeypatch.setattr(offline, "installed_tool", lambda name: executable)
    return {
        "archive_path": str(archive),
        "expected_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "graph_identifier": "Material",
        "output_dir": str(tmp_path / "fresh"),
        "resolution": 256,
        "outputs": [
            {"name": "Height", "bit_depth": 16, "color_space": "Raw"},
            {"name": "Metallic", "bit_depth": 8, "color_space": "Raw"},
        ],
    }


def _render(command, log, **_kwargs):
    if command[1] == "info":
        log.write_text("GRAPH-URL pkg://Material\n  OUTPUT Height height\n  OUTPUT Metallic metallic\n")
        return
    target = Path(command[command.index("--output-path") + 1])
    assert "sbsrender" in Path(command[0]).name
    assert command[command.index("--inputs") + 1].endswith("material.sbsar")
    assert "Height@16" in command and "Metallic@8" in command
    for name, depth in (("Height", 16), ("Metallic", 8)):
        (target / (name + ".png")).write_bytes(_png(depth))
    log.write_text("test fake process log")


def test_pinned_render_publishes_complete_verified_files_and_accepts_constants(render_request, monkeypatch):
    monkeypatch.setattr(offline, "run_artifact_command", _render)
    result = offline.render_archive(**render_request)
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest == result["artifact"]
    assert manifest["native_rerender_exact"] is True
    assert manifest["designer_session_verified"] is False
    for item in manifest["files"]:
        path = Path(result["output_dir"]) / "maps" / item["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    assert not list(Path(result["output_dir"]).parent.glob(".designer-render-*"))


def test_gpu_engine_is_a_fixed_installed_hashed_library(render_request, monkeypatch):
    engine = Path(render_request["archive_path"]).parent / "plugins/engines/substance_d3d11_blend.dll"
    engine.write_bytes(b"test-only fixed GPU engine identity")
    commands = []

    def render(command, log, **kwargs):
        if command[1] == "render":
            commands.append(command)
            assert command[command.index("--engine") + 1] == str(engine.resolve())
        _render(command, log, **kwargs)

    monkeypatch.setattr(offline, "run_artifact_command", render)
    result = offline.render_archive(**render_request, engine="d3d11")
    assert len(commands) == 2
    assert result["artifact"]["engine"] == {
        "identifier": "d3d11",
        "file": engine.name,
        "sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
    }


@pytest.mark.parametrize("engine", ["../evil.dll", "auto", "D3D11", True])
def test_caller_cannot_select_arbitrary_engine_libraries(render_request, monkeypatch, engine):
    monkeypatch.setattr(offline, "run_artifact_command", lambda *_args, **_kwargs: pytest.fail("Run after preflight"))
    with pytest.raises(GraphAuthoringError, match="engine identifier"):
        offline.render_archive(**render_request, engine=engine)
    assert not Path(render_request["output_dir"]).exists()


def test_uninstalled_engine_cannot_fall_back_to_cpu(render_request, monkeypatch):
    monkeypatch.setattr(offline, "run_artifact_command", lambda *_args, **_kwargs: pytest.fail("Run after preflight"))
    with pytest.raises(GraphAuthoringError) as error:
        offline.render_archive(**render_request, engine="d3d11")
    assert error.value.code == "OFFLINE_ENGINE_UNAVAILABLE"
    assert not Path(render_request["output_dir"]).exists()


def test_engine_change_during_render_cannot_publish(render_request, monkeypatch):
    engine = Path(render_request["archive_path"]).parent / "plugins/engines/substance_sse2_blend.dll"

    def render(command, log, **kwargs):
        _render(command, log, **kwargs)
        if command[1] == "render":
            engine.write_bytes(b"changed engine after first native render")

    monkeypatch.setattr(offline, "run_artifact_command", render)
    with pytest.raises(GraphAuthoringError) as error:
        offline.render_archive(**render_request)
    assert error.value.code == "INPUT_HASH_CHANGED"
    assert not Path(render_request["output_dir"]).exists()


def test_native_renderer_help_has_only_fixed_arguments(render_request, monkeypatch):
    def native_help(command, log, **kwargs):
        assert command[1:] == ["render", "--help"] and kwargs["timeout"] == 30
        log.write_text("Official render help: --engine sse2 d3d11")

    monkeypatch.setattr(offline, "run_artifact_command", native_help)
    result = offline.inspect_renderer()
    assert result["route"] == "official CLI"
    assert result["installed_engines"][0]["identifier"] == "sse2"
    assert "no GPU render claim" in result["engine_availability_scope"]


def test_file_operation_error_retains_bounded_os_diagnostics():
    from dcc_mcp_substance3d_designer.skill_support import typed_result

    def fail():
        raise PermissionError(13, "private operation detail", "private-directory/owned-file.exr")

    result = typed_result("render", fail)
    assert result["error"] == "PermissionError"
    assert result["context"]["errno"] == 13
    assert result["context"]["file"] == "owned-file.exr"
    assert "private-directory" not in json.dumps(result)


@pytest.mark.parametrize(
    "kind,code",
    [
        ("hash", "INPUT_HASH_CHANGED"),
        ("collision", "OUTPUT_EXISTS"),
        ("depth", "INVALID_OFFLINE_REQUEST"),
        ("duplicate", "INVALID_OFFLINE_REQUEST"),
    ],
)
def test_preflight_never_calls_native_or_overwrites_owned_inputs(render_request, monkeypatch, kind, code):
    archive = Path(render_request["archive_path"])
    original = archive.read_bytes()
    if kind == "hash":
        render_request["expected_archive_sha256"] = "0" * 64
    elif kind == "collision":
        Path(render_request["output_dir"]).mkdir()
        (Path(render_request["output_dir"]) / "sentinel").write_bytes(b"previous case")
    elif kind == "depth":
        render_request["outputs"][0]["bit_depth"] = True
    else:
        render_request["outputs"][1]["name"] = "height"
    monkeypatch.setattr(
        offline, "run_artifact_command", lambda *args, **kwargs: pytest.fail("Preflight must run first")
    )
    with pytest.raises(GraphAuthoringError) as error:
        offline.render_archive(**render_request)
    assert error.value.code == code
    assert archive.read_bytes() == original


@pytest.mark.parametrize(
    "kind,code",
    [
        ("missing", "OFFLINE_OUTPUT_MISSING"),
        ("truncated", "MAP_HEADER_INVALID"),
        ("rerender", "RERENDER_CHANGED"),
        ("failed", "OFFLINE_PROCESS_FAILED"),
    ],
)
def test_false_native_success_cannot_publish_a_manifest(render_request, monkeypatch, kind, code):
    def render(command, log, **kwargs):
        if kind == "failed":
            raise GraphAuthoringError("test native timeout/cleanup failure", code)
        _render(command, log, **kwargs)
        if command[1] == "info":
            return
        target = Path(command[command.index("--output-path") + 1])
        if kind == "missing":
            (target / "Height.png").unlink()
        elif kind == "truncated":
            (target / "Height.png").write_bytes(_png(16)[:33])
        elif target.name == "readback":
            (target / "Height.png").write_bytes(_png(16, value=1))

    monkeypatch.setattr(offline, "run_artifact_command", render)
    with pytest.raises(GraphAuthoringError) as error:
        offline.render_archive(**render_request)
    assert error.value.code == code
    assert not Path(render_request["output_dir"]).exists()
    assert not list(Path(render_request["output_dir"]).parent.glob(".designer-render-*"))


def test_cook_hashes_actual_archive_and_keeps_source_relative_dependency_context(render_request, monkeypatch):
    source = Path(render_request["archive_path"]).with_suffix(".sbs")
    source.write_bytes(b"test-only SBS source")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    native_sources = []

    def cook(command, log, **kwargs):
        native_source = Path(command[command.index("--inputs") + 1])
        native_sources.append(native_source)
        assert native_source != source and native_source.parent == source.parent
        assert native_source.read_bytes() == source.read_bytes()
        assert kwargs["timeout"] == 300
        output = Path(command[command.index("--output-path") + 1])
        assert (output / "source.sbs").read_bytes() == source.read_bytes()
        # A mutable original cannot determine what the cooker actually reads.
        original = source.read_bytes()
        source.write_bytes(b"transient unpinned edit")
        (output / "material.sbsar").write_bytes(native_source.read_bytes())
        source.write_bytes(original)
        log.write_text("test fake process log")

    monkeypatch.setattr(offline, "run_artifact_command", cook)
    result = offline.cook_package(str(source), source_sha, render_request["output_dir"])
    assert result["artifact"]["archive"]["sha256"] == source_sha
    assert result["artifact"]["source_dependency_hashes_collected"] is False
    assert all(not path.exists() for path in native_sources)


def test_failed_cook_removes_only_its_owned_source_snapshot(render_request, monkeypatch):
    source = Path(render_request["archive_path"]).with_suffix(".sbs")
    source.write_bytes(b"test-only SBS source")
    native_sources = []

    def fail(command, log, **kwargs):
        native_sources.append(Path(command[command.index("--inputs") + 1]))
        raise GraphAuthoringError("test native failure", "OFFLINE_PROCESS_FAILED")

    monkeypatch.setattr(offline, "run_artifact_command", fail)
    with pytest.raises(GraphAuthoringError, match="test native failure"):
        offline.cook_package(str(source), hashlib.sha256(source.read_bytes()).hexdigest(), render_request["output_dir"])
    assert source.read_bytes() == b"test-only SBS source"
    assert native_sources and all(not path.exists() for path in native_sources)
    assert not Path(render_request["output_dir"]).exists()


def test_fixed_archive_does_not_silently_accept_an_unexposed_seed(render_request, monkeypatch):
    monkeypatch.setattr(offline, "run_artifact_command", _render)
    with pytest.raises(GraphAuthoringError) as error:
        offline.render_archive(**render_request, seed=137)
    assert error.value.code == "ARCHIVE_INTERFACE_CHANGED"
    assert not Path(render_request["output_dir"]).exists()


def test_image_readback_validates_the_snapshot_used_by_native_render(render_request, monkeypatch):
    source = Path(render_request["archive_path"]).with_suffix(".png")
    data = _png()
    source.write_bytes(data)
    checked = []
    verify = offline.verify_png

    def readback(path, *args):
        assert path != source
        # Changing the mutable caller input cannot change validated/rendered pixels.
        source.write_bytes(b"transient unpinned caller edit")
        try:
            result = verify(path, *args)
            checked.append(path)
            return result
        finally:
            source.write_bytes(data)

    def native(command, log, **kwargs):
        _render(command, log, **kwargs)
        if command[1] == "info":
            with log.open("a") as stream:
                stream.write("  INPUT Position IMAGE\n")

    monkeypatch.setattr(offline, "verify_png", readback)
    monkeypatch.setattr(offline, "run_artifact_command", native)
    result = offline.render_archive(
        **render_request,
        input_images=[
            {"name": "Position", "path": str(source), "sha256": hashlib.sha256(data).hexdigest(), "color_space": "Raw"}
        ],
    )
    assert checked[0].name == "input_Position.png"
    assert result["artifact"]["native_rerender_exact"]
    assert source.read_bytes() == data


def test_standalone_options_never_bind_an_optional_gui_pid(monkeypatch):
    from dcc_mcp_core.server_base import DccServerBase

    from dcc_mcp_substance3d_designer.offline_server import DesignerOfflineServer

    monkeypatch.setattr(DccServerBase, "__init__", lambda self, *, options: self.__dict__.update(test_options=options))
    server = DesignerOfflineServer(enable_gateway_failover=False)
    options = server.test_options
    assert options.instance_type == "standalone"
    assert options.diagnostics.dcc_pid is None
    assert options.execution.mode.kind == "inline"
    assert options.builtin_skills_dir.name == "designer-offline"


def test_async_output_contract_accepts_the_real_core_poll_envelope():
    import jsonschema
    import yaml

    tools = yaml.safe_load((Path(offline.__file__).parent / "skills/designer-offline/tools.yaml").read_text())["tools"]
    queued = {
        "job_id": "actual-core-owned-id",
        "core_job_id": "actual-core-owned-id",
        "job_id_owner": "core",
        "status": "pending",
        "core_poll": {"owner": "core", "tool": "jobs_get_status"},
    }
    for tool in tools:
        if tool["execution"] == "async":
            jsonschema.validate(queued, tool["output_schema"])
        else:
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(queued, tool["output_schema"])
        jsonschema.validate({"success": True, "message": "Finished", "context": {}}, tool["output_schema"])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"status": "success"}, tool["output_schema"])


def test_subprocess_skill_entry_emits_a_real_error_instead_of_empty_success(render_request, tmp_path):
    arguments = dict(render_request, expected_archive_sha256="0" * 64)
    script = Path(offline.__file__).parent / "skills/designer-offline/scripts/render_archive.py"
    source_root = Path(offline.__file__).parent.parent
    environment = dict(os.environ, PYTHONPATH=str(source_root))
    process = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(arguments),
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        timeout=30,
        check=False,
    )
    assert process.returncode == 1
    actual = json.loads(process.stdout)
    assert actual["success"] is False
    assert actual["error"] == "INPUT_HASH_CHANGED"
