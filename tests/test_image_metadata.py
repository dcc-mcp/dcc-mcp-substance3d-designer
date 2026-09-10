import struct
import zlib

import pytest

from dcc_mcp_substance3d_designer.graph_authoring import GraphAuthoringError
from dcc_mcp_substance3d_designer.image_metadata import read_image_metadata


def png_header(depth=16):
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">IIBBBBB", 128, 64, depth, 2, 0, 0, 0)
    return header + struct.pack(">I", zlib.crc32(header[12:]))


def test_png_actual_depth_and_dimensions(tmp_path):
    path = tmp_path / "map.png"
    path.write_bytes(png_header())
    assert read_image_metadata(path, "png", "16") == {
        "width": 128,
        "height": 64,
        "channels": 3,
        "bit_depth": "16",
        "format": "png",
    }
    with pytest.raises(GraphAuthoringError):
        read_image_metadata(path, "png", "8")


@pytest.mark.parametrize("fmt", ["png", "tga", "tiff", "exr"])
def test_wrong_or_truncated_header_rejected(tmp_path, fmt):
    path = tmp_path / "map"
    for payload in (b"", b"not an image", png_header()[:22]):
        path.write_bytes(payload)
        with pytest.raises(GraphAuthoringError):
            read_image_metadata(path, fmt, "16")


def test_tga_channel_depth(tmp_path):
    path = tmp_path / "map.tga"
    path.write_bytes(bytes([0, 0, 2]) + bytes(9) + struct.pack("<HHBB", 128, 64, 24, 0))
    assert read_image_metadata(path, "tga", "8")["channels"] == 3


def test_tiff_float_sample_format(tmp_path):
    path = tmp_path / "map.tiff"
    entries = [(256, 128), (257, 64), (258, 32), (277, 1), (339, 3)]
    path.write_bytes(
        b"II"
        + struct.pack("<HIH", 42, 8, len(entries))
        + b"".join(struct.pack("<HHII", tag, 4, 1, value) for tag, value in entries)
        + bytes(4)
    )
    assert read_image_metadata(path, "tiff", "32f")["bit_depth"] == "32f"
    with pytest.raises(GraphAuthoringError):
        read_image_metadata(path, "tiff", "16f")


def test_exr_half_channels(tmp_path):
    def attribute(name, kind, payload):
        return name + b"\0" + kind + b"\0" + struct.pack("<I", len(payload)) + payload

    channels = b"R\0" + struct.pack("<iB3xii", 1, 0, 1, 1) + b"\0"
    payload = (
        b"v/1\x01"
        + struct.pack("<I", 2)
        + attribute(b"dataWindow", b"box2i", struct.pack("<4i", 0, 0, 127, 63))
        + attribute(b"channels", b"chlist", channels)
        + b"\0"
    )
    path = tmp_path / "map.exr"
    path.write_bytes(payload)
    assert read_image_metadata(path, "exr", "16f")["width"] == 128
    with pytest.raises(GraphAuthoringError):
        read_image_metadata(path, "exr", "32f")
