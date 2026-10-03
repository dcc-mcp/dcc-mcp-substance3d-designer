"""Narrow official mesh-position baking and complete floating-point readback.

The operator supplies installed binaries. The decoder reads native EXR pixels;
it does not author texture pixels or prove UV coverage or biological accuracy.
"""

from __future__ import annotations

import array
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

from .image_metadata import read_image_metadata
from .offline_artifacts import (
    _RESOLUTIONS,
    _destination,
    _error,
    _file,
    _pinned,
    _publish,
    _sha,
    _snapshot,
    installed_tool,
)
from .render_process import run_artifact_command


def _mesh(path):
    """Reject external materials, nontriangles, invalid indices and missing UVs."""
    points, uvs, triangles = [], [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        kind = fields[0]
        if kind in ("v", "vt"):
            width = 3 if kind == "v" else 2
            values = [float(value) for value in fields[1:]]
            if len(values) not in ((3,) if kind == "v" else (2, 3)) or not all(map(math.isfinite, values)):
                _error("Mesh coordinates must be finite and explicit")
            if kind == "vt" and (
                not all(0 <= value <= 1 for value in values[:2]) or (len(values) == 3 and values[2] != 0)
            ):
                _error("Position baking supports one normalized UV tile")
            (points if kind == "v" else uvs).append(values[:width])
        elif kind == "f":
            if len(fields) != 4:
                _error("Position baking requires triangulated OBJ faces")
            for corner in fields[1:]:
                indices = corner.split("/")
                if len(indices) < 2 or not indices[0].isdigit() or not indices[1].isdigit():
                    _error("Every triangle corner requires positive point and UV indices")
                if not 1 <= int(indices[0]) <= len(points) or not 1 <= int(indices[1]) <= len(uvs):
                    _error("Triangle indices exceed mesh arrays")
            triangles += 1
        elif kind in ("mtllib", "usemtl"):
            _error("Position mesh must be self-contained without external materials")
        elif kind not in ("vn", "o", "g", "s"):
            _error("Unsupported OBJ statement for position baking")
    if not points or not uvs or not triangles:
        _error("Position baking requires points, UV coordinates and triangles")
    minimum = [min(point[axis] for point in points) for axis in range(3)]
    maximum = [max(point[axis] for point in points) for axis in range(3)]
    if any(low == high for low, high in zip(minimum, maximum)):
        _error("Bounding-box normalized position requires three nonzero extents")
    return {
        "points": len(points),
        "triangles": triangles,
        "uv_coordinates": len(uvs),
        "bounds": {"minimum": minimum, "maximum": maximum},
        "uv_set": 0,
    }


def verify_position_exr(path, resolution, directory, timeout=300):
    """Decode every RGB sample using a fixed, operator-configured FFmpeg binary."""
    metadata = read_image_metadata(path, "exr", None)
    if (
        metadata["width"] != resolution
        or metadata["height"] != resolution
        or metadata["channels"] not in (3, 4)
        or metadata["bit_depth"] not in ("16f", "32f")
    ):
        _error("Position EXR dimensions/precision differ from the contract", "MAP_HEADER_INVALID")
    configured = os.environ.get("DCC_MCP_SUBSTANCE3D_DESIGNER_FFMPEG")
    if not configured:
        _error("Configure installed FFmpeg for complete native EXR readback", "OFFLINE_TOOLS_UNAVAILABLE")
    decoder = Path(configured).expanduser().resolve(strict=True)
    if not decoder.is_file():
        _error("Configured EXR decoder is unavailable", "OFFLINE_TOOLS_UNAVAILABLE")
    decoder_sha = _sha(decoder)
    with tempfile.TemporaryDirectory(prefix=".exr-readback-", dir=directory) as temporary:
        target = Path(temporary) / "pixels.f32"
        command = [
            str(decoder),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "gbrpf32le",
            "-f",
            "rawvideo",
            str(target),
        ]
        run_artifact_command(command, Path(temporary) / "decode.log", timeout=timeout)
        if not target.is_file() or target.stat().st_size != resolution * resolution * 3 * 4:
            _error("EXR decoder did not read the complete image", "MAP_HEADER_INVALID")
        bits = array.array("I")
        with target.open("rb") as stream:
            bits.fromfile(stream, resolution * resolution * 3)
        if sys.byteorder != "little":
            bits.byteswap()
        # Nonnegative normalized IEEE float values have monotone bit patterns.
        # This rejects NaN, infinity, negative values and values above one.
        if any(value > 0x3F800000 for value in bits):
            _error("Position EXR contains nonfinite/out-of-range samples", "MAP_HEADER_INVALID")
        low, high = (struct.unpack("<f", struct.pack("<I", value))[0] for value in (min(bits), max(bits)))
    if _sha(decoder) != decoder_sha:
        _error("Configured decoder changed during readback", "INPUT_HASH_CHANGED")
    return dict(
        metadata,
        complete_rgb_readback=True,
        finite=True,
        rgb_range=[low, high],
        decoder={"name": decoder.name, "sha256": decoder_sha},
    )


def bake_position_map(
    mesh_path: str,
    expected_mesh_sha256: str,
    output_dir: str,
    resolution: int = 2048,
    padding_radius: int = 4,
    timeout_seconds: int = 300,
) -> dict:
    """Bake bbox-normalized XYZ/UV0 twice; preserve native warnings and argv."""
    if (
        type(resolution) is not int
        or resolution not in _RESOLUTIONS
        or type(padding_radius) is not int
        or not 0 <= padding_radius <= 32
    ):
        _error("Unsupported position resolution or bounded padding radius")
    mesh = _pinned(mesh_path, expected_mesh_sha256, ".obj")
    topology = _mesh(mesh)
    executable = installed_tool("substance3d_baker")
    tool_hash = _sha(executable)
    destination = _destination(output_dir)
    with tempfile.TemporaryDirectory(prefix=".designer-position-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "artifacts"
        staging.mkdir()
        snapshot = staging / "mesh.obj"
        _snapshot(mesh, snapshot, expected_mesh_sha256)
        # Validate the exact owned bytes passed to the baker, including the
        # semantic mesh counts/bounds recorded in its receipt.
        topology = _mesh(snapshot)
        commands, warnings, readbacks = [], [], []
        for attempt in ("maps", "readback"):
            target = staging / attempt
            target.mkdir()
            command = [
                str(executable),
                "Position.Rasterised",
                "--inputs",
                str(snapshot),
                "--cpu",
                "--base.uv_set",
                "0",
                "--mode",
                "all_axes",
                "--normalization",
                "bbox",
                "--normalization_scale",
                "full_scene",
                "--output_format",
                "exr",
                "--output_size",
                f"{resolution},{resolution}",
                "--output_name",
                "RestPosition",
                "--output_path",
                str(target),
                "--padding_radius",
                str(padding_radius),
                "--enable_mip_diffusion",
                "false",
                "--texture_cache_size",
                "1024",
            ]
            log = staging / (attempt + ".log")
            run_artifact_command(command, log, timeout=timeout_seconds)
            lines = log.read_text(encoding="utf-8").splitlines()
            warnings.extend({"attempt": attempt, "message": line} for line in lines if "[WARNING]" in line)
            if any("[ERROR]" in line for line in lines):
                _error("Official baker reported an error", "OFFLINE_PROCESS_FAILED")
            if {file.name for file in target.iterdir()} != {"RestPosition.exr"}:
                _error("Position baker produced an unexpected output set", "OFFLINE_OUTPUT_MISSING")
            path = target / "RestPosition.exr"
            _file(path)
            readbacks.append(verify_position_exr(path, resolution, staging, timeout_seconds))
            commands.append(command)
            if _sha(snapshot) != expected_mesh_sha256:
                _error("Owned mesh snapshot changed during baking", "INPUT_HASH_CHANGED")
        if (staging / "maps/RestPosition.exr").read_bytes() != (staging / "readback/RestPosition.exr").read_bytes():
            _error("Native position rerender changed actual EXR bytes", "RERENDER_CHANGED")
        if _sha(mesh) != expected_mesh_sha256 or _sha(executable) != tool_hash:
            _error("Input/tool changed during position baking", "INPUT_HASH_CHANGED")
        receipt = {
            "schema": "dcc-mcp.designer-position.v1",
            "mesh_sha256": expected_mesh_sha256,
            "mesh": topology,
            "position": _file(staging / "maps/RestPosition.exr"),
            "image_metadata": readbacks[0],
            "resolution": resolution,
            "padding_radius": padding_radius,
            "position_encoding": "bbox-normalized XYZ in RGB; UV0; full_scene",
            "normalization_bounds": topology["bounds"],
            "native_rerender_exact": True,
            "native_warnings": warnings,
            "native_argv": commands,
            "tool": {"name": executable.name, "sha256": tool_hash},
            "route": "official CLI",
            "raster_postprocessing": False,
            "native_uv_padding": True,
            "native_mip_diffusion": False,
            "geometry_uv_correspondence_accepted": False,
            "designer_session_verified": False,
        }
        return _publish(staging, destination, receipt)
