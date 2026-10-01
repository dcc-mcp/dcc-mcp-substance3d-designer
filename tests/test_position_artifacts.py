"""Native readback guards distinguish complete finite positions from headers."""

import hashlib
import struct
from pathlib import Path

import pytest

from dcc_mcp_substance3d_designer import position_artifacts as position
from dcc_mcp_substance3d_designer.graph_authoring import GraphAuthoringError


@pytest.mark.parametrize("defect", [None, "nan", "truncated", "negative", "above_one"])
def test_full_decoder_samples_are_required_not_an_exr_header(tmp_path, monkeypatch, defect):
    decoder, source = tmp_path / "ffmpeg", tmp_path / "positions.exr"
    decoder.write_bytes(b"test-only decoder identity")
    source.write_bytes(b"test-only EXR; metadata and decoder are deliberately mocked")
    monkeypatch.setenv("DCC_MCP_SUBSTANCE3D_DESIGNER_FFMPEG", str(decoder))
    monkeypatch.setattr(
        position,
        "read_image_metadata",
        lambda *a: {"width": 256, "height": 256, "channels": 4, "bit_depth": "16f", "format": "exr"},
    )

    def decode(command, log, **kwargs):
        data = struct.pack("<f", 0.5) * (256 * 256 * 3)
        if defect in ("nan", "negative", "above_one"):
            data = struct.pack("<f", {"nan": float("nan"), "negative": -0.1, "above_one": 1.1}[defect]) + data[4:]
        Path(command[-1]).write_bytes(data[:-4] if defect == "truncated" else data)

    monkeypatch.setattr(position, "run_artifact_command", decode)
    if defect:
        with pytest.raises(GraphAuthoringError) as failure:
            position.verify_position_exr(source, 256, tmp_path)
        assert failure.value.code == "MAP_HEADER_INVALID"
    else:
        result = position.verify_position_exr(source, 256, tmp_path)
        assert result["complete_rgb_readback"] and result["rgb_range"] == [0.5, 0.5]
    assert not list(tmp_path.glob(".exr-readback-*"))


def test_mesh_bake_reads_owned_snapshot_and_preserves_native_warnings(tmp_path, monkeypatch):
    source, executable = tmp_path / "input.obj", tmp_path / "substance3d_baker"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 1\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n")
    executable.write_bytes(b"test-only official binary identity")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(position, "installed_tool", lambda name: executable)
    monkeypatch.setattr(position, "verify_position_exr", lambda *args: {"complete_rgb_readback": True, "finite": True})

    def bake(command, log, **kwargs):
        native = Path(command[command.index("--inputs") + 1])
        assert native != source and native.read_bytes() == source.read_bytes()
        assert command[1] == "Position.Rasterised" and "--cpu" in command
        assert command[command.index("--enable_mip_diffusion") + 1] == "false"
        target = Path(command[command.index("--output_path") + 1])
        (target / "RestPosition.exr").write_bytes(b"test native result; readback mocked")
        log.write_text("[WARNING][USD]preserve this native diagnostic\n")

    monkeypatch.setattr(position, "run_artifact_command", bake)
    result = position.bake_position_map(str(source), sha, str(tmp_path / "fresh"), 256)
    receipt = result["artifact"]
    assert receipt["mesh"]["points"] == 3 and receipt["mesh"]["triangles"] == 1
    assert len(receipt["native_warnings"]) == 2 and len(receipt["native_argv"]) == 2
    assert receipt["native_rerender_exact"] and not receipt["geometry_uv_correspondence_accepted"]
    with pytest.raises(GraphAuthoringError, match="fresh"):
        position.bake_position_map(str(source), sha, str(tmp_path / "fresh"), 256)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == sha


@pytest.mark.parametrize("statement", ["f 1 2 3", "f 1/1 2/2 4/3", "mtllib outside.mtl", "vt nan 0"])
def test_invalid_or_external_mesh_inputs_cannot_start_native(tmp_path, monkeypatch, statement):
    source = tmp_path / "invalid.obj"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 1\nvt 0 0\nvt 1 0\nvt 0 1\n" + statement + "\n")
    monkeypatch.setattr(position, "installed_tool", lambda *a: pytest.fail("Preflight must reject the mesh"))
    with pytest.raises((GraphAuthoringError, ValueError)):
        position.bake_position_map(
            str(source), hashlib.sha256(source.read_bytes()).hexdigest(), str(tmp_path / "fresh")
        )


@pytest.mark.parametrize("defect", ["snapshot", "rerender"])
def test_changed_snapshot_or_native_pixels_cannot_publish(tmp_path, monkeypatch, defect):
    source, executable = tmp_path / "input.obj", tmp_path / "substance3d_baker"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 1\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n")
    executable.write_bytes(b"test-only binary")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(position, "installed_tool", lambda name: executable)
    monkeypatch.setattr(position, "verify_position_exr", lambda *args: {"complete_rgb_readback": True})

    def bake(command, log, **kwargs):
        native = Path(command[command.index("--inputs") + 1])
        target = Path(command[command.index("--output_path") + 1])
        (target / "RestPosition.exr").write_bytes(b"changed" if target.name == "readback" else b"native")
        if defect == "snapshot":
            native.write_bytes(b"transient different mesh")
        log.write_text("test native log")

    monkeypatch.setattr(position, "run_artifact_command", bake)
    with pytest.raises(GraphAuthoringError) as failure:
        position.bake_position_map(str(source), sha, str(tmp_path / "fresh"), 256)
    assert failure.value.code == ("INPUT_HASH_CHANGED" if defect == "snapshot" else "RERENDER_CHANGED")
    assert not (tmp_path / "fresh").exists()
    assert source.read_text().startswith("v 0 0 0")
