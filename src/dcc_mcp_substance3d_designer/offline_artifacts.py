"""Hash-pinned official CLI artifacts, independent of a Designer SDK session.

The configured installed binaries generate all pixels. Input hashes, complete
PNG validation and a second render prove local artifacts, not material accuracy
or a live Designer session. Source dependencies are not independently pinned.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
import zlib
from pathlib import Path

from .graph_authoring import GraphAuthoringError
from .image_metadata import read_image_metadata
from .render_process import run_artifact_command

_HASH = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}")
_MAX_BYTES = 128 * 1024 * 1024
_RESOLUTIONS = (256, 512, 1024, 2048, 4096)


def _error(message, code="INVALID_OFFLINE_REQUEST"):
    raise GraphAuthoringError(message, code)


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pinned(path, expected, suffix):
    if not isinstance(expected, str) or _HASH.fullmatch(expected) is None:
        _error("Input requires an explicit lowercase SHA256")
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() != suffix or not 0 < source.stat().st_size <= _MAX_BYTES:
        _error("Input must be a bounded nonempty " + suffix + " file")
    if _sha(source) != expected:
        _error("Input bytes differ from the expected hash", "INPUT_HASH_CHANGED")
    return source


def _identifier(value):
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        _error("Use a bounded graph/output/input identifier")
    return value


def _destination(value):
    destination = Path(value).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        _error("Use a fresh output directory", "OUTPUT_EXISTS")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def installed_tool(name):
    """Resolve only a fixed official tool name from operator-owned configuration."""
    configured = os.environ.get("DCC_MCP_SUBSTANCE3D_DESIGNER_BIN")
    if not configured:
        _error("Configure the installed Designer CLI bin directory", "OFFLINE_TOOLS_UNAVAILABLE")
    path = Path(configured).expanduser().resolve() / (name + (".exe" if os.name == "nt" else ""))
    if not path.is_file():
        _error("Installed official CLI tool is unavailable: " + name, "OFFLINE_TOOLS_UNAVAILABLE")
    return path


def _snapshot(source, destination, expected):
    shutil.copyfile(source, destination)
    if _sha(destination) != expected:
        _error("Input changed while taking the owned snapshot", "INPUT_HASH_CHANGED")


def _file(path):
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= _MAX_BYTES:
        _error("Official CLI did not produce a bounded artifact", "OFFLINE_OUTPUT_MISSING")
    return {"file": path.name, "sha256": _sha(path), "bytes": path.stat().st_size}


def verify_png(path, depth, resolution):
    """Read all chunks, CRCs and scanlines; reject a valid header on a partial PNG."""
    metadata = read_image_metadata(path, "png", str(depth))
    if (metadata["width"], metadata["height"]) != (resolution, resolution):
        _error("PNG dimensions differ from the requested resolution", "MAP_HEADER_INVALID")
    data = path.read_bytes()
    if len(data) > _MAX_BYTES:
        _error("PNG exceeds the artifact budget", "MAP_HEADER_INVALID")
    offset, compressed, ended, first = 8, bytearray(), False, True
    try:
        while offset < len(data):
            length = struct.unpack_from(">I", data, offset)[0]
            kind = data[offset + 4 : offset + 8]
            end = offset + 12 + length
            if end > len(data) or zlib.crc32(data[offset + 4 : end - 4]) != struct.unpack_from(">I", data, end - 4)[0]:
                raise ValueError("PNG chunk length/checksum")
            payload = data[offset + 8 : end - 4]
            if first:
                if kind != b"IHDR" or length != 13 or payload[-3:] != b"\0\0\0":
                    raise ValueError("Only noninterlaced native PNG is supported")
                first = False
            elif kind == b"IHDR":
                raise ValueError("Duplicate PNG header")
            if kind == b"IDAT":
                compressed.extend(payload)
            if kind == b"IEND":
                if length or end != len(data):
                    raise ValueError("PNG terminal chunk")
                ended = True
            offset = end
        if not ended or not compressed:
            raise ValueError("Incomplete PNG")
        row = resolution * metadata["channels"] * depth // 8 + 1
        expected = row * resolution
        decoder = zlib.decompressobj()
        scanlines = decoder.decompress(compressed, expected + 1)
        if (
            not decoder.eof
            or decoder.unused_data
            or len(scanlines) != expected
            or any(scanlines[index] > 4 for index in range(0, expected, row))
        ):
            raise ValueError("PNG compressed scanline contract")
    except (ValueError, struct.error, zlib.error) as exc:
        raise GraphAuthoringError("Native PNG is incomplete or corrupt", "MAP_HEADER_INVALID") from exc
    return metadata


def _publish(staging, destination, receipt):
    receipt_path = staging / "manifest.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if destination.exists() or destination.is_symlink():
        _error("Output directory appeared before publication", "OUTPUT_EXISTS")
    staging.rename(destination)
    return {
        "output_dir": str(destination),
        "manifest_path": str(destination / receipt_path.name),
        "manifest_sha256": _sha(destination / receipt_path.name),
        "artifact": receipt,
    }


def cook_package(
    source_path: str,
    expected_source_sha256: str,
    output_dir: str,
    max_resolution: int = 2048,
    timeout_seconds: int = 300,
) -> dict:
    """Cook an unchanged SBS source; publish only verified owned artifacts."""
    if type(max_resolution) is not int or max_resolution not in _RESOLUTIONS:
        _error("Unsupported cook resolution budget")
    source = _pinned(source_path, expected_source_sha256, ".sbs")
    executable = installed_tool("sbscooker")
    tool_hash = _sha(executable)
    destination = _destination(output_dir)
    with tempfile.TemporaryDirectory(prefix=".designer-cook-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "artifacts"
        staging.mkdir()
        _snapshot(source, staging / "source.sbs", expected_source_sha256)
        # Preserve relative source dependencies by cooking at the original path.
        command = [
            str(executable),
            "--inputs",
            str(source),
            "--output-path",
            str(staging),
            "--output-name",
            "material",
            "--consistent-header",
            "1",
            "--size-limit",
            str(max_resolution.bit_length() - 1),
        ]
        run_artifact_command(command, staging / "cook.log", timeout=timeout_seconds)
        if _sha(source) != expected_source_sha256 or _sha(executable) != tool_hash:
            _error("Source or configured tool changed during cooking", "INPUT_HASH_CHANGED")
        archive = _file(staging / "material.sbsar")
        receipt = {
            "schema": "dcc-mcp.designer-cook.v1",
            "source_sha256": expected_source_sha256,
            "archive": archive,
            "tool": {"name": executable.name, "sha256": tool_hash},
            "max_resolution": max_resolution,
            "source_dependency_hashes_collected": False,
            "route": "official CLI",
            "designer_session_verified": False,
        }
        return _publish(staging, destination, receipt)


def render_archive(
    archive_path: str,
    expected_archive_sha256: str,
    graph_identifier: str,
    output_dir: str,
    outputs: list[dict],
    resolution: int = 1024,
    seed: int | None = None,
    input_images: list[dict] | None = None,
    normal_convention: str | None = None,
    timeout_seconds: int = 300,
) -> dict:
    """Render one pinned SBSAR twice; keep channel units caller-declared."""
    graph_identifier = _identifier(graph_identifier)
    if (
        type(resolution) is not int
        or resolution not in _RESOLUTIONS
        or (seed is not None and (type(seed) is not int or not 0 <= seed < 2**31))
        or normal_convention not in (None, "OpenGL (+Y)", "DirectX (-Y)")
    ):
        _error("Unsupported resolution, seed or tangent normal convention")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 8:
        _error("Select one to eight explicit outputs")
    names = set()
    for item in outputs:
        if not isinstance(item, dict) or set(item) != {"name", "bit_depth", "color_space"}:
            _error("Every output requires only name, bit_depth and color_space")
        name = _identifier(item["name"])
        if name.casefold() in names or type(item["bit_depth"]) is not int or item["bit_depth"] not in (8, 16):
            _error("Output names must be unique and depths must be 8 or 16")
        if item["color_space"] not in ("Raw", "sRGB"):
            _error("Output color space must be explicit Raw or sRGB")
        names.add(name.casefold())
    images, names = [], set()
    if input_images is not None and (not isinstance(input_images, list) or len(input_images) > 8):
        _error("Select up to eight explicit PNG inputs")
    for item in input_images or []:
        if not isinstance(item, dict) or set(item) != {"name", "path", "sha256", "color_space"}:
            _error("Each image requires name, path, sha256 and color_space")
        name = _identifier(item["name"])
        if name.casefold() in names or item["color_space"] not in ("Raw", "sRGB"):
            _error("Input names must be unique and color spaces explicit")
        names.add(name.casefold())
        path = _pinned(item["path"], item["sha256"], ".png")
        metadata = read_image_metadata(path, "png", None)
        if metadata["width"] != metadata["height"] or metadata["width"] not in _RESOLUTIONS:
            _error("Image input must be square and within the resolution budget")
        verify_png(path, int(metadata["bit_depth"]), metadata["width"])
        images.append((item, path))
    archive = _pinned(archive_path, expected_archive_sha256, ".sbsar")
    executable = installed_tool("sbsrender")
    tool_hash = _sha(executable)
    destination = _destination(output_dir)
    with tempfile.TemporaryDirectory(prefix=".designer-render-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "artifacts"
        staging.mkdir()
        snapshot = staging / "material.sbsar"
        _snapshot(archive, snapshot, expected_archive_sha256)
        interface_log = staging / "archive-info.log"
        run_artifact_command([str(executable), "info", "--input", str(snapshot)], interface_log, timeout=30)
        interface = interface_log.read_text(encoding="utf-8")
        blocks = re.split(r"(?m)^GRAPH-URL ", interface)
        selected = [block for block in blocks[1:] if block.splitlines()[0].strip() == "pkg://" + graph_identifier]
        if len(selected) != 1:
            _error("Compiled archive does not identify the requested graph", "ARCHIVE_INTERFACE_CHANGED")
        native_outputs = set(re.findall(r"(?m)^\s+OUTPUT (\S+)", selected[0]))
        native_inputs = set(re.findall(r"(?m)^\s+INPUT (\S+)", selected[0]))
        if native_outputs != {item["name"] for item in outputs}:
            _error("Declared output set differs from compiled archive interface", "ARCHIVE_INTERFACE_CHANGED")
        if seed is not None and "$randomseed" not in native_inputs:
            _error("Compiled graph does not expose a randomseed override", "ARCHIVE_INTERFACE_CHANGED")
        if any(item["name"] not in native_inputs for item, _ in images):
            _error("Image input is not exposed by the compiled graph", "ARCHIVE_INTERFACE_CHANGED")
        input_files = []
        for item, path in images:
            target = staging / ("input_" + item["name"] + ".png")
            _snapshot(path, target, item["sha256"])
            input_files.append((item, target))
        files = []
        for attempt in ("maps", "readback"):
            target = staging / attempt
            target.mkdir()
            exponent = resolution.bit_length() - 1
            command = [
                str(executable),
                "render",
                "--inputs",
                str(snapshot),
                "--input-graph",
                graph_identifier,
                "--output-path",
                str(target),
                "--output-name",
                "{outputNodeName}",
                "--output-format",
                "png",
                "--engine",
                "sse2",
                "--cpu-count",
                "4",
            ]
            if "$outputsize" in native_inputs:
                command.extend(["--set-value", f"$outputsize@{exponent},{exponent}"])
            if seed is not None:
                command.extend(["--set-value", f"$randomseed@{seed}"])
            for item in outputs:
                command.extend(
                    [
                        "--set-output-bit-depth",
                        f"{item['name']}@{item['bit_depth']}",
                        "--set-output-colorspace",
                        f"{item['name']}@{item['color_space']}",
                    ]
                )
            for item, path in input_files:
                command.extend(
                    [
                        "--set-entry",
                        f"{item['name']}@{path}",
                        "--set-entry-colorspace",
                        f"{item['name']}@{item['color_space']}",
                    ]
                )
            run_artifact_command(command, staging / (attempt + ".log"), timeout=timeout_seconds)
            if {path.name for path in target.iterdir()} != {item["name"] + ".png" for item in outputs}:
                _error("Native archive outputs differ from the exact declared channel set", "OFFLINE_OUTPUT_MISSING")
            for item in outputs:
                path = target / (item["name"] + ".png")
                description = _file(path)
                metadata = verify_png(path, item["bit_depth"], resolution)
                if attempt == "maps":
                    files.append(
                        dict(description, name=item["name"], color_space=item["color_space"], image_metadata=metadata)
                    )
                if attempt == "readback" and path.read_bytes() != (staging / "maps" / path.name).read_bytes():
                    _error("Native rerender changed actual output bytes", "RERENDER_CHANGED")
        if _sha(executable) != tool_hash:
            _error("Configured tool changed during rendering", "INPUT_HASH_CHANGED")
        receipt = {
            "schema": "dcc-mcp.designer-render.v1",
            "archive_sha256": expected_archive_sha256,
            "graph_identifier": graph_identifier,
            "resolution": resolution,
            "seed_override": seed,
            "parameter_policy": "No undeclared numeric/image input overrides; fixed archive defaults otherwise",
            "native_archive_interface": selected[0].splitlines(),
            "files": files,
            "inputs": [
                {"name": item["name"], "sha256": item["sha256"], "color_space": item["color_space"]}
                for item, _ in input_files
            ],
            "tool": {"name": executable.name, "sha256": tool_hash},
            "native_rerender_exact": True,
            "normal_convention": normal_convention,
            "normal_convention_source": "caller declaration",
            "route": "official CLI",
            "raster_postprocessing": False,
            "designer_session_verified": False,
        }
        return _publish(staging, destination, receipt)
