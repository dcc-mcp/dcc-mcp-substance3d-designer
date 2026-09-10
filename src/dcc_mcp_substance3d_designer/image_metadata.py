"""Bounded metadata validation for SAT export formats; not a pixel decoder."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from .graph_authoring import GraphAuthoringError

_HEADER_LIMIT = 65536


def read_image_metadata(path: Path, image_format: str, bit_depth: str | None) -> dict:
    with path.open("rb") as stream:
        data = stream.read(_HEADER_LIMIT)
    try:
        if image_format == "png":
            if data[:8] != b"\x89PNG\r\n\x1a\n" or data[8:16] != b"\x00\x00\x00\rIHDR":
                raise ValueError("PNG header")
            width, height, bits, color = struct.unpack_from(">IIBB", data, 16)
            if bits not in (8, 16) or zlib.crc32(data[12:29]) != struct.unpack_from(">I", data, 29)[0]:
                raise ValueError("PNG IHDR depth or checksum")
            channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
            depth = str(bits)
        elif image_format == "tga":
            if len(data) < 18 or data[1] != 0 or data[2] not in (2, 3, 10, 11):
                raise ValueError("TGA header")
            width, height, bits = struct.unpack_from("<HHB", data, 12)
            channels = 1 if data[2] in (3, 11) else (4 if bits == 32 else 3)
            if bits != channels * 8:
                raise ValueError("TGA depth")
            depth = "8"
        elif image_format == "tiff":
            endian = {b"II": "<", b"MM": ">"}[data[:2]]
            if struct.unpack_from(endian + "H", data, 2)[0] != 42:
                raise ValueError("TIFF header")
            offset = struct.unpack_from(endian + "I", data, 4)[0]
            count = struct.unpack_from(endian + "H", data, offset)[0]
            if count > 256:
                raise ValueError("TIFF IFD limit")
            tags = {}
            for index in range(count):
                entry = offset + 2 + 12 * index
                tag, kind, size = struct.unpack_from(endian + "HHI", data, entry)
                if tag not in (256, 257, 258, 277, 339):
                    continue
                unit, fmt = {3: (2, "H"), 4: (4, "I")}[kind]
                if not 1 <= size <= 4:
                    raise ValueError("TIFF channel limit")
                location = entry + 8 if size * unit <= 4 else struct.unpack_from(endian + "I", data, entry + 8)[0]
                tags[tag] = struct.unpack_from(endian + fmt * size, data, location)
            width, height = tags[256][0], tags[257][0]
            channels = tags.get(277, (1,))[0]
            bits, sample = set(tags[258]), set(tags.get(339, (1,)))
            if len(bits) != 1 or len(sample) != 1 or next(iter(sample)) not in (1, 3):
                raise ValueError("TIFF mixed sample representation")
            depth = str(next(iter(bits))) + ("f" if sample == {3} else "")
        elif image_format == "exr":
            if data[:4] != b"v/1\x01":
                raise ValueError("EXR header")
            version = struct.unpack_from("<I", data, 4)[0]
            if version & 0x1800:  # Multipart and non-image/deep require another parser.
                raise ValueError("Unsupported EXR parts")
            offset, attributes = 8, {}
            while data[offset] != 0:
                end = data.index(0, offset)
                name = data[offset:end].decode("ascii")
                offset = end + 1
                end = data.index(0, offset)
                kind = data[offset:end]
                length = struct.unpack_from("<I", data, end + 1)[0]
                offset = end + 5
                if length > _HEADER_LIMIT or offset + length > len(data):
                    raise ValueError("EXR attribute limit")
                attributes[name] = (kind, data[offset : offset + length])
                offset += length
            if attributes["dataWindow"][0] != b"box2i" or attributes["channels"][0] != b"chlist":
                raise ValueError("EXR attributes")
            x0, y0, x1, y1 = struct.unpack("<4i", attributes["dataWindow"][1])
            width, height = x1 - x0 + 1, y1 - y0 + 1
            channel_data, cursor, types = attributes["channels"][1], 0, []
            while channel_data[cursor] != 0:
                end = channel_data.index(0, cursor)
                pixel_type = struct.unpack_from("<i", channel_data, end + 1)[0]
                types.append({1: "16f", 2: "32f"}[pixel_type])
                cursor = end + 17
                if len(types) > 4:
                    raise ValueError("EXR channel limit")
            channels = len(types)
            if len(set(types)) != 1:
                raise ValueError("EXR mixed channel depth")
            depth = types[0]
        else:
            raise ValueError("Unsupported image format")
        if (
            not 0 < width <= 32768
            or not 0 < height <= 32768
            or not 1 <= channels <= 4
            or (bit_depth is not None and depth != bit_depth)
        ):
            raise ValueError("Image dimensions or bit depth differ from export contract")
    except (ValueError, KeyError, IndexError, struct.error) as exc:
        raise GraphAuthoringError(
            "Exported image header does not satisfy its format/depth contract", "MAP_HEADER_INVALID"
        ) from exc
    return {"width": width, "height": height, "channels": channels, "bit_depth": depth, "format": image_format}
