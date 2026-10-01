"""Read installed baker capabilities and bake explicit native FBX colour IDs.

The adapter does not infer regions, rewrite FBX data or guarantee geometry/UV
correspondence. Callers validate ID colours against their indexed geometry.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .graph_authoring import GraphAuthoringError
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
    verify_png,
)
from .render_process import run_artifact_command

_BAKERS = ("Color.Raytraced", "Position.Rasterised")
_COLOR_SOURCES = ("vertex", "mesh_color")


def inspect_mesh_baker(baker: str = "Color.Raytraced") -> dict:
    """Return bounded installed help; no caller-selected executables or argv."""
    if baker not in _BAKERS:
        _error("Choose a supported native mesh baker")
    executable = installed_tool("substance3d_baker")
    identity = _sha(executable)
    with tempfile.TemporaryDirectory(prefix="designer-baker-help-") as temporary:
        log = Path(temporary) / "help.log"
        run_artifact_command([str(executable), baker, "--help"], log, timeout=30)
        help_text = log.read_text(encoding="utf-8")
        if not help_text.strip() or len(help_text.encode("utf-8")) > 131072:
            _error("Installed baker help is empty or exceeds the bounded contract", "OFFLINE_OUTPUT_MISSING")
    if _sha(executable) != identity:
        _error("Configured baker changed during capability readback", "INPUT_HASH_CHANGED")
    return {
        "schema": "dcc-mcp.designer-baker-help.v1",
        "baker": baker,
        "help": help_text,
        "tool": {"name": executable.name, "sha256": identity},
        "route": "official CLI",
        "designer_session_verified": False,
    }


def _fbx(path: Path) -> None:
    with path.open("rb") as stream:
        header = stream.read(128)
    if not (header.startswith(b"Kaydara FBX Binary  \x00\x1a\x00") or header.lstrip().startswith(b"; FBX")):
        _error("Colour ID baking requires a native binary or ASCII FBX", "INVALID_COLOR_MESH")


def bake_color_map(
    mesh_path: str,
    expected_mesh_sha256: str,
    output_dir: str,
    color_source: str = "vertex",
    resolution: int = 2048,
    padding_radius: int = 4,
    timeout_seconds: int = 300,
) -> dict:
    """Bake caller-authored FBX vertex/material colours twice using UV0.

    Uses the exact same owned mesh as low and high geometry. The native projection
    distances are explicit bbox fractions, and mip diffusion is disabled. This is
    not anatomy recognition or an independently parsed topology acceptance.
    """
    if (
        color_source not in _COLOR_SOURCES
        or type(resolution) is not int
        or resolution not in _RESOLUTIONS
        or type(padding_radius) is not int
        or not 0 <= padding_radius <= 32
    ):
        _error("Choose explicit vertex/material colour IDs and a supported resolution/padding")
    mesh = _pinned(mesh_path, expected_mesh_sha256, ".fbx")
    _fbx(mesh)
    executable = installed_tool("substance3d_baker")
    tool_hash = _sha(executable)
    destination = _destination(output_dir)
    with tempfile.TemporaryDirectory(prefix=".designer-color-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "artifacts"
        staging.mkdir()
        snapshot = staging / "mesh.fbx"
        _snapshot(mesh, snapshot, expected_mesh_sha256)
        _fbx(snapshot)
        commands, warnings, metadata = [], [], []
        for attempt in ("maps", "readback"):
            target = staging / attempt
            target.mkdir()
            command = [
                str(executable),
                "Color.Raytraced",
                "--inputs",
                str(snapshot),
                "--cpu",
                "--base.uv_set",
                "0",
                "--use_lowdef_as_highdef",
                "true",
                "--color_source",
                color_source,
                "--projection.normalized_distance",
                "true",
                "--projection.max_height",
                "0.0001",
                "--projection.max_depth",
                "0.0001",
                "--projection.smooth_normals",
                "false",
                "--output_format",
                "png",
                "--output_size",
                f"{resolution},{resolution}",
                "--output_name",
                "ColorID",
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
            try:
                run_artifact_command(command, log, timeout=timeout_seconds)
            except GraphAuthoringError as exc:
                native = log.read_text(encoding="utf-8")[-2048:] if log.is_file() else "Native log unavailable"
                raise GraphAuthoringError(str(exc) + "; native diagnostic: " + native, exc.code) from exc
            lines = log.read_text(encoding="utf-8").splitlines()
            warnings.extend({"attempt": attempt, "message": line} for line in lines if "[WARNING]" in line)
            if any("[ERROR]" in line for line in lines):
                _error("Official colour baker reported an error", "OFFLINE_PROCESS_FAILED")
            attribute = "VertexColor" if color_source == "vertex" else "MaterialColor"
            if any("missing" in line.lower() and attribute in line for line in lines):
                _error("Native mesh lacks the requested " + attribute + " attribute", "COLOR_ATTRIBUTE_MISSING")
            if {file.name for file in target.iterdir()} != {"ColorID.png"}:
                _error("Colour baker produced an unexpected output set", "OFFLINE_OUTPUT_MISSING")
            path = target / "ColorID.png"
            native_metadata = read_image_metadata(path, "png", None)
            metadata.append(verify_png(path, int(native_metadata["bit_depth"]), resolution))
            commands.append(command)
            if _sha(snapshot) != expected_mesh_sha256:
                _error("Owned mesh snapshot changed during colour baking", "INPUT_HASH_CHANGED")
        if (staging / "maps/ColorID.png").read_bytes() != (staging / "readback/ColorID.png").read_bytes():
            _error("Native colour rerender changed actual PNG bytes", "RERENDER_CHANGED")
        if _sha(mesh) != expected_mesh_sha256 or _sha(executable) != tool_hash:
            _error("Input/tool changed during colour baking", "INPUT_HASH_CHANGED")
        receipt = {
            "schema": "dcc-mcp.designer-color.v1",
            "mesh_sha256": expected_mesh_sha256,
            "color_source": color_source,
            "color": _file(staging / "maps/ColorID.png"),
            "image_metadata": metadata[0],
            "resolution": resolution,
            "padding_radius": padding_radius,
            "uv_set": 0,
            "projection": {
                "use_lowdef_as_highdef": True,
                "normalized_distance": True,
                "max_height": 0.0001,
                "max_depth": 0.0001,
                "smooth_normals": False,
            },
            "native_rerender_exact": True,
            "native_warnings": warnings,
            "native_argv": commands,
            "tool": {"name": executable.name, "sha256": tool_hash},
            "route": "official CLI",
            "raster_postprocessing": False,
            "native_uv_padding": True,
            "native_mip_diffusion": False,
            "geometry_uv_correspondence_accepted": False,
            "anatomy_recognition_performed": False,
            "designer_session_verified": False,
        }
        return _publish(staging, destination, receipt)
