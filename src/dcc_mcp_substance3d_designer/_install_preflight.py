"""Host, interpreter, version, and existing-state preflight."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from dcc_mcp_substance3d_designer.__version__ import __version__
from dcc_mcp_substance3d_designer._install_io import hash_file, load_json
from dcc_mcp_substance3d_designer._install_model import (
    INSTALL_ROOT_ENV,
    MIN_CORE_VERSION,
    MIN_DESIGNER_VERSION,
    PLUGIN_NAME,
    PYTHON_ENV,
    VERSION_ENV,
    InstallContext,
    LifecycleFailure,
)


def version_tuple(value: str) -> Tuple[int, ...]:
    match = re.search(r"\d+(?:\.\d+)+", value)
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


def query_python(python_path: Path) -> Dict[str, str]:
    script = (
        "import json,sys,sysconfig; "
        "import dcc_mcp_core,dcc_mcp_substance3d_designer as adapter; "
        "print(json.dumps({'python_version':'.'.join(map(str,sys.version_info[:3])),"
        "'python_root':sysconfig.get_path('purelib'),'core_version':dcc_mcp_core.__version__,"
        "'adapter_version':adapter.__version__}))"
    )
    try:
        completed = subprocess.run(
            [str(python_path), "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleFailure("python", f"Target interpreter could not run: {exc}") from exc
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip().splitlines()
        message = details[-1] if details else f"exit {completed.returncode}"
        raise LifecycleFailure("python", f"Target interpreter import check failed: {message}")
    try:
        result = json.loads(completed.stdout)
    except ValueError as exc:
        raise LifecycleFailure("python", "Target interpreter returned invalid metadata.") from exc
    if result.get("adapter_version") != __version__:
        raise LifecycleFailure("python", "Target interpreter does not contain this adapter version.")
    if version_tuple(str(result.get("core_version", ""))) < version_tuple(MIN_CORE_VERSION):
        raise LifecycleFailure("core_version", f"dcc-mcp-core>={MIN_CORE_VERSION} is required.")
    return {str(key): str(value) for key, value in result.items()}


def _host_candidates(environ: Mapping[str, str]) -> Sequence[Path]:
    candidates = []
    if os.name == "nt":
        for key in ("ProgramFiles", "ProgramW6432"):
            root = environ.get(key, "").strip()
            if root:
                candidates.extend(
                    (Path(root) / "Adobe").glob("Adobe Substance 3D Designer*/Adobe Substance 3D Designer.exe")
                )
    elif sys.platform == "darwin":
        candidates.append(
            Path("/Applications/Adobe Substance 3D Designer.app/Contents/MacOS/Adobe Substance 3D Designer")
        )
    else:
        candidates.extend(
            [
                Path("/opt/Adobe/Adobe Substance 3D Designer/Adobe Substance 3D Designer"),
                Path("/usr/bin/substance3d-designer"),
            ]
        )
        discovered = shutil.which("substance3d-designer")
        if discovered:
            candidates.append(Path(discovered))
    unique = {candidate.expanduser().resolve() for candidate in candidates if candidate.is_file()}
    return tuple(sorted(unique, key=str))


def _resolve_host_path(dcc_path: Optional[str], environ: Mapping[str, str]) -> Path:
    if dcc_path:
        candidate = Path(dcc_path).expanduser().resolve()
        if candidate.is_dir() and candidate.suffix.lower() == ".app":
            candidate = candidate / "Contents" / "MacOS" / "Adobe Substance 3D Designer"
        if candidate.is_file():
            return candidate
        raise LifecycleFailure("host", f"Designer executable does not exist: {candidate}")
    candidates = _host_candidates(environ)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise LifecycleFailure("host", "Designer was not found in a standard install location; pass --dcc-path.")
    raise LifecycleFailure("host", "Multiple Designer installations were found; select one with --dcc-path.")


def _windows_file_version(path: Path) -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, data):
            return None
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [
                ("signature", wintypes.DWORD),
                ("structure_version", wintypes.DWORD),
                ("file_version_ms", wintypes.DWORD),
                ("file_version_ls", wintypes.DWORD),
                ("product_version_ms", wintypes.DWORD),
                ("product_version_ls", wintypes.DWORD),
                ("file_flags_mask", wintypes.DWORD),
                ("file_flags", wintypes.DWORD),
                ("file_os", wintypes.DWORD),
                ("file_type", wintypes.DWORD),
                ("file_subtype", wintypes.DWORD),
                ("file_date_ms", wintypes.DWORD),
                ("file_date_ls", wintypes.DWORD),
            ]

        info = ctypes.cast(pointer, ctypes.POINTER(FixedFileInfo)).contents
        parts = (
            info.product_version_ms >> 16,
            info.product_version_ms & 0xFFFF,
            info.product_version_ls >> 16,
            info.product_version_ls & 0xFFFF,
        )
        return ".".join(str(part) for part in parts)
    except (AttributeError, OSError, ValueError):
        return None


def _detect_host_version(path: Path, environ: Mapping[str, str]) -> Tuple[str, str]:
    override = environ.get(VERSION_ENV, "").strip()
    if override:
        return override, VERSION_ENV
    file_version = _windows_file_version(path)
    if file_version:
        return file_version, "file_metadata"
    if path.parent.name == "MacOS" and path.parent.parent.name == "Contents":
        try:
            metadata = plistlib.loads((path.parent.parent / "Info.plist").read_bytes())
            version = str(metadata.get("CFBundleShortVersionString") or metadata.get("CFBundleVersion") or "").strip()
        except (OSError, ValueError):
            version = ""
        if version:
            return version, "app_bundle"
    match = re.search(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)", str(path))
    if match:
        return match.group(1), "path"
    return "", "unavailable"


def _detect_embedded_python_version(path: Path, host_version: str) -> Tuple[str, str]:
    roots = [path.parent / "plugins" / "pythonsdk"]
    if path.parent.name == "MacOS" and path.parent.parent.name == "Contents":
        roots.insert(0, path.parent.parent / "plugins" / "pythonsdk")
    discovered = set()
    for root in roots:
        for parent in (root / "lib", root / "include"):
            for candidate in parent.glob("python*"):
                match = re.fullmatch(r"python(\d+\.\d+)", candidate.name)
                if candidate.is_dir() and match:
                    discovered.add(match.group(1))
    if len(discovered) == 1:
        return discovered.pop(), "installation"
    if len(discovered) > 1:
        raise LifecycleFailure(
            "python_compatibility",
            "Designer contains multiple embedded Python SDK versions; select an unambiguous installation.",
        )
    major = version_tuple(host_version)[0]
    return ("3.11", "release_matrix") if major >= 14 else ("3.9", "release_matrix")


def resolve_context(dcc_path: Optional[str], python_path: Optional[str], environ: Mapping[str, str]) -> InstallContext:
    host = _resolve_host_path(dcc_path, environ)
    host_version, host_version_source = _detect_host_version(host, environ)
    if not host_version or version_tuple(host_version) < MIN_DESIGNER_VERSION:
        raise LifecycleFailure("host_version", "Designer 12.1 or newer is required and must be identifiable.")
    embedded_python_version, embedded_python_version_source = _detect_embedded_python_version(host, host_version)
    selected_python = python_path or environ.get(PYTHON_ENV) or sys.executable
    interpreter = Path(selected_python).expanduser().resolve()
    if not interpreter.is_file():
        raise LifecycleFailure("python", f"Target interpreter does not exist: {interpreter}")
    python = query_python(interpreter)
    target_python = ".".join(python["python_version"].split(".")[:2])
    if target_python != embedded_python_version:
        raise LifecycleFailure(
            "python_compatibility",
            f"Designer embedded Python {embedded_python_version}, but --python uses {target_python}.",
        )
    install_root = (
        Path(environ.get(INSTALL_ROOT_ENV) or Path.home() / ".dcc-mcp" / "substance3d_designer").expanduser().resolve()
    )
    suffix = ".cmd" if os.name == "nt" else ".sh"
    receipt_path = install_root / "receipts" / "substance3d_designer.json"
    launcher_path = install_root / "launchers" / f"substance3d_designer{suffix}"
    payload_root = install_root / "payload"
    plugin_path = payload_root / "plugins" / PLUGIN_NAME
    receipt_exists = receipt_path.is_file()
    artifacts_exist = launcher_path.exists() or payload_root.exists()
    if artifacts_exist and not receipt_exists:
        state = "partial"
    elif receipt_exists:
        receipt = load_json(receipt_path)
        files = receipt.get("files", [])
        intact = bool(files)
        for item in files:
            path = Path(str(item.get("path", "")))
            if not path.is_file() or hash_file(path) != item.get("sha256"):
                intact = False
                break
        if receipt.get("adapter_version") != __version__:
            state = "upgrade"
        else:
            state = "current" if intact else "repair"
    else:
        state = "fresh"
    return InstallContext(
        host_path=host,
        host_version=host_version,
        host_version_source=host_version_source,
        embedded_python_version=embedded_python_version,
        embedded_python_version_source=embedded_python_version_source,
        python_path=interpreter,
        python_version=python["python_version"],
        python_root=Path(python["python_root"]).resolve(),
        core_version=python["core_version"],
        install_root=install_root,
        receipt_path=receipt_path,
        launcher_path=launcher_path,
        payload_root=payload_root,
        plugin_path=plugin_path,
        bootstrap_log_dir=install_root / "logs",
        state=state,
    )


__all__ = ["query_python", "resolve_context"]
