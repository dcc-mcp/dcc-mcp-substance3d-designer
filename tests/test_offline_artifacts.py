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

    def cook(command, log, **kwargs):
        assert command[command.index("--inputs") + 1] == str(source)
        assert kwargs["timeout"] == 300
        output = Path(command[command.index("--output-path") + 1])
        assert (output / "source.sbs").read_bytes() == source.read_bytes()
        (output / "material.sbsar").write_bytes(b"actual fake-runner output")
        log.write_text("test fake process log")

    monkeypatch.setattr(offline, "run_artifact_command", cook)
    result = offline.cook_package(str(source), source_sha, render_request["output_dir"])
    assert result["artifact"]["archive"]["sha256"] == hashlib.sha256(b"actual fake-runner output").hexdigest()
    assert result["artifact"]["source_dependency_hashes_collected"] is False


def test_fixed_archive_does_not_silently_accept_an_unexposed_seed(render_request, monkeypatch):
    monkeypatch.setattr(offline, "run_artifact_command", _render)
    with pytest.raises(GraphAuthoringError) as error:
        offline.render_archive(**render_request, seed=137)
    assert error.value.code == "ARCHIVE_INTERFACE_CHANGED"
    assert not Path(render_request["output_dir"]).exists()


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
