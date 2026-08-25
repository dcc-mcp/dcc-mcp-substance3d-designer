"""Receipt and atomic file primitives for the Designer lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from dcc_mcp_core.deployment import INSTALL_EXIT_INSTALL

from dcc_mcp_substance3d_designer._install_model import LifecycleFailure

_MAX_RECEIPT_BYTES = 1024 * 1024


def _is_link_or_junction(path: Path) -> bool:
    junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(junction and junction())


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.is_file() or _is_link_or_junction(path) or not 0 < path.stat().st_size <= _MAX_RECEIPT_BYTES:
            raise ValueError("invalid receipt")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LifecycleFailure("receipt", "Designer receipt is unreadable or unbounded.") from exc
    if not isinstance(payload, dict):
        raise LifecycleFailure("receipt", "Receipt root must be a JSON object.")
    return payload


def write_bytes_atomic(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    primary: Optional[BaseException] = None
    try:
        temporary.write_bytes(payload)
        temporary.chmod(mode)
        os.replace(str(temporary), str(path))
    except BaseException as exc:
        primary = exc
    if temporary.exists():
        try:
            temporary.unlink()
        except OSError as cleanup_error:
            raise LifecycleFailure(
                "cleanup",
                "Designer atomic file cleanup did not complete.",
                INSTALL_EXIT_INSTALL,
            ) from cleanup_error
    if primary is not None:
        raise primary


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_bytes_atomic(path, encoded)


__all__ = ["hash_file", "load_json", "write_bytes_atomic", "write_json_atomic"]
