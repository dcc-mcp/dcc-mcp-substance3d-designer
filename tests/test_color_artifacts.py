"""Owned input, native pixel and executable identity guards for colour IDs."""

import hashlib
import struct
import zlib
from pathlib import Path

import pytest

from dcc_mcp_substance3d_designer import color_artifacts as color
from dcc_mcp_substance3d_designer.graph_authoring import GraphAuthoringError


def _png(path, rgb):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress((b"\x00" + bytes(rgb) * 256) * 256)) + chunk(b"IEND", b"")
    path.write_bytes(data)


def _input(tmp_path, monkeypatch):
    mesh, executable = tmp_path / "native.fbx", tmp_path / "substance3d_baker"
    mesh.write_bytes(b"Kaydara FBX Binary  \x00\x1a\x00test-only native input; baker is mocked")
    executable.write_bytes(b"test-only installed tool identity")
    monkeypatch.setattr(color, "installed_tool", lambda name: executable)
    return mesh, executable, hashlib.sha256(mesh.read_bytes()).hexdigest()


def test_bounded_installed_baker_help_has_tool_identity(tmp_path, monkeypatch):
    _, executable, _ = _input(tmp_path, monkeypatch)

    def help_command(command, log, **kwargs):
        assert command == [str(executable), "Color.Raytraced", "--help"]
        log.write_text("test-only native help --color_source vertex mesh_color")

    monkeypatch.setattr(color, "run_artifact_command", help_command)
    receipt = color.inspect_mesh_baker()
    assert receipt["baker"] == "Color.Raytraced" and receipt["tool"]["sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()
    with pytest.raises(GraphAuthoringError):
        color.inspect_mesh_baker("arbitrary command")


@pytest.mark.parametrize("color_source", ["vertex", "mesh_color"])
def test_native_color_pixels_repeat_and_keep_warning_evidence(tmp_path, monkeypatch, color_source):
    mesh, _, sha = _input(tmp_path, monkeypatch)

    def bake(command, log, **kwargs):
        native = Path(command[command.index("--inputs") + 1])
        assert native != mesh and native.read_bytes() == mesh.read_bytes()
        assert command[1] == "Color.Raytraced" and command[command.index("--color_source") + 1] == color_source
        assert command[command.index("--use_lowdef_as_highdef") + 1] == "true"
        target = Path(command[command.index("--output_path") + 1])
        _png(target / "ColorID.png", (30, 70, 90))
        log.write_text("[WARNING]Retain this native colour diagnostic\n")

    monkeypatch.setattr(color, "run_artifact_command", bake)
    result = color.bake_color_map(str(mesh), sha, str(tmp_path / "accepted"), color_source, 256)
    artifact = result["artifact"]
    assert artifact["native_rerender_exact"] and len(artifact["native_warnings"]) == 2
    assert artifact["image_metadata"]["channels"] == 3
    assert artifact["color_source"] == color_source and not artifact["geometry_uv_correspondence_accepted"]
    assert hashlib.sha256(mesh.read_bytes()).hexdigest() == sha


@pytest.mark.parametrize("defect", ["snapshot", "rerender", "header", "warning_error"])
def test_changed_native_input_or_pixels_cannot_publish(tmp_path, monkeypatch, defect):
    mesh, _, sha = _input(tmp_path, monkeypatch)

    def bake(command, log, **kwargs):
        native = Path(command[command.index("--inputs") + 1])
        target = Path(command[command.index("--output_path") + 1])
        _png(target / "ColorID.png", (10 if target.name == "maps" else 20, 30, 40) if defect == "rerender" else (10, 30, 40))
        if defect == "snapshot":
            native.write_bytes(b"changed owned input")
        elif defect == "header":
            (target / "ColorID.png").write_bytes(b"invalid incomplete native PNG")
        log.write_text("[ERROR]native bake error" if defect == "warning_error" else "test-only native log")

    monkeypatch.setattr(color, "run_artifact_command", bake)
    with pytest.raises(GraphAuthoringError):
        color.bake_color_map(str(mesh), sha, str(tmp_path / "rejected"), resolution=256)
    assert not (tmp_path / "rejected").exists()


def test_unknown_region_source_and_invalid_fbx_never_start_native(tmp_path, monkeypatch):
    mesh = tmp_path / "wrong.fbx"
    mesh.write_bytes(b"not an FBX")
    sha = hashlib.sha256(mesh.read_bytes()).hexdigest()
    monkeypatch.setattr(color, "installed_tool", lambda *args: pytest.fail("Reject before native launch"))
    for source in ("coordinate_guess", "vertex"):
        with pytest.raises(GraphAuthoringError):
            color.bake_color_map(str(mesh), sha, str(tmp_path / "rejected"), color_source=source)


@pytest.mark.parametrize("source,attribute", [("vertex", "VertexColor"), ("mesh_color", "MaterialColor")])
def test_requested_native_color_attribute_missing_cannot_publish(tmp_path, monkeypatch, source, attribute):
    mesh, _, sha = _input(tmp_path, monkeypatch)

    def bake(command, log, **kwargs):
        target = Path(command[command.index("--output_path") + 1])
        _png(target / "ColorID.png", (255, 255, 255))
        log.write_text("[WARNING][Bakers]mesh is missing some optional attribute(s): " + attribute)

    monkeypatch.setattr(color, "run_artifact_command", bake)
    with pytest.raises(GraphAuthoringError) as failure:
        color.bake_color_map(str(mesh), sha, str(tmp_path / "rejected"), source, 256)
    assert failure.value.code == "COLOR_ATTRIBUTE_MISSING"
    assert not (tmp_path / "rejected").exists()


def test_retained_native_png_is_complete_16_bit_not_silently_quantized():
    fixture = Path(__file__).parent / "fixtures/native-color"
    png = fixture / "ColorID.png"
    assert hashlib.sha256(png.read_bytes()).hexdigest() == "df8739b04319fa72dfc2e51df9bc911a2994fd3bc276090f9f8ef12bf09b311a"
    metadata = color.verify_png(png, 16, 256)
    assert metadata["channels"] == 4 and metadata["bit_depth"] == "16"
    with pytest.raises(GraphAuthoringError):
        color.verify_png(png, 8, 256)


def test_launch_failure_keeps_the_bounded_process_reason(tmp_path, monkeypatch):
    from dcc_mcp_substance3d_designer import render_process

    monkeypatch.setattr(render_process, "_run_bounded_command_in_root",
                        lambda *args, **kwargs: {"success": False, "reason": "launch failed: PermissionError"})
    with pytest.raises(GraphAuthoringError, match="PermissionError"):
        render_process.run_artifact_command(["test-only-unexecuted"], tmp_path / "error.log")
