"""Host, interpreter, version, provenance, and existing-state preflight."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import plistlib
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit

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
from dcc_mcp_substance3d_designer._install_process import run_bounded_command as _run_bounded_command

_MAX_VERSION_LENGTH = 32
_MAX_MODULE_BYTES = 8 * 1024 * 1024
_VERSION_COMPONENT_RE = re.compile(r"(?:0|[1-9][0-9]{0,5})")
_HOST_EXECUTABLES = {"adobe substance 3d designer.exe", "adobe substance 3d designer", "substance3d-designer"}


def version_tuple(value: object, *, components: int = 3) -> Optional[Tuple[int, ...]]:
    """Parse a bounded canonical final version before integer conversion."""
    if not isinstance(value, str) or not 0 < len(value) <= _MAX_VERSION_LENGTH:
        return None
    parts = value.split(".")
    if len(parts) != components or any(_VERSION_COMPONENT_RE.fullmatch(part) is None for part in parts):
        return None
    parsed = tuple(int(part) for part in parts)
    return parsed if any(parsed) else None


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _is_link_or_junction(path: Path) -> bool:
    junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(junction and junction())


def _require_regular_file(path: Path, stage: str, label: str) -> Path:
    try:
        if not path.is_file() or _is_link_or_junction(path) or path.stat().st_size <= 0:
            raise LifecycleFailure(stage, f"{label} is missing, empty, or an unsupported link.")
    except OSError as exc:
        raise LifecycleFailure(stage, f"{label} could not be inspected.") from exc
    return path.resolve()


def _editable_distribution_root(value: object) -> Optional[Path]:
    if not isinstance(value, dict) or not isinstance(value.get("dir_info"), dict):
        return None
    url = value.get("url")
    if value["dir_info"].get("editable") is not True or not isinstance(url, str) or not 0 < len(url) <= 2048:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "file" or parsed.query or parsed.fragment:
        return None
    raw_path = unquote(parsed.path)
    if re.fullmatch(r"/[A-Za-z]:/.*", raw_path):
        raw_path = raw_path[1:]
    try:
        root = Path(raw_path).resolve()
    except (OSError, ValueError):
        return None
    return root if root.is_dir() and not _is_link_or_junction(root) else None


def _require_distribution_origin(
    module_file: Path,
    root_value: object,
    record_value: object,
    record_hash: object,
    record_size: object,
    direct_url: object,
    trusted_roots: Sequence[Path],
    *,
    distribution: str,
    package: str,
) -> None:
    root_text = str(root_value or "")
    root = Path(root_text)
    if (
        not root_text
        or not root.is_dir()
        or _is_link_or_junction(root)
        or not any(_same_path(root, trusted) for trusted in trusted_roots)
        or module_file.name != "__init__.py"
        or module_file.parent.name != package
    ):
        raise LifecycleFailure("python", f"Imported {distribution} module is shadowed outside its distribution.")
    if isinstance(record_value, str) and 0 < len(record_value) <= 1024:
        record_path = Path(record_value)
        if record_path.is_absolute() or ".." in record_path.parts:
            raise LifecycleFailure("python", f"Imported {distribution} distribution is outside selected site-packages.")
        if not _same_path(root / record_path, module_file) or not _path_within(module_file, root):
            raise LifecycleFailure("python", f"Imported {distribution} module is not owned by its RECORD.")
        if (
            not isinstance(record_hash, str)
            or not record_hash.startswith("sha256=")
            or not isinstance(record_size, int)
            or isinstance(record_size, bool)
            or not 0 < record_size <= _MAX_MODULE_BYTES
            or module_file.stat().st_size != record_size
        ):
            raise LifecycleFailure("python", f"Imported {distribution} module has invalid RECORD integrity.")
        expected = record_hash.removeprefix("sha256=")
        actual = (
            base64.urlsafe_b64encode(hashlib.sha256(module_file.read_bytes()).digest()).rstrip(b"=").decode("ascii")
        )
        if not expected or actual != expected:
            raise LifecycleFailure("python", f"Imported {distribution} module failed RECORD integrity.")
        return
    editable = _editable_distribution_root(direct_url)
    candidates = (
        () if editable is None else (editable / "src" / package / "__init__.py", editable / package / "__init__.py")
    )
    if not any(_same_path(module_file, candidate) for candidate in candidates):
        raise LifecycleFailure("python", f"Imported {distribution} module has no validated distribution ownership.")


def _require_distribution_artifact(
    artifact: Path,
    root_value: object,
    record_value: object,
    record_hash: object,
    record_size: object,
    *,
    distribution: str,
) -> None:
    root = Path(str(root_value or ""))
    if not root.is_dir() or _is_link_or_junction(root) or not isinstance(record_value, str):
        raise LifecycleFailure("python", f"Imported {distribution} artifact has no distribution ownership.")
    if (
        not 0 < len(record_value) <= 1024
        or Path(record_value).is_absolute()
        or not _same_path(root / record_value, artifact)
    ):
        raise LifecycleFailure("python", f"Imported {distribution} artifact is not owned by its RECORD.")
    if (
        not isinstance(record_hash, str)
        or not record_hash.startswith("sha256=")
        or not isinstance(record_size, int)
        or isinstance(record_size, bool)
        or not 0 < record_size <= 512 * 1024 * 1024
        or artifact.stat().st_size != record_size
    ):
        raise LifecycleFailure("python", f"Imported {distribution} artifact has invalid RECORD integrity.")
    expected = record_hash.removeprefix("sha256=")
    actual = base64.urlsafe_b64encode(hashlib.sha256(artifact.read_bytes()).digest()).rstrip(b"=").decode("ascii")
    if not expected or actual != expected:
        raise LifecycleFailure("python", f"Imported {distribution} artifact failed RECORD integrity.")


def query_python(python_path: Path) -> Dict[str, str]:
    script = r"""
import importlib.metadata as md
import json
import os
import pathlib
import re
import sys
import sysconfig
import urllib.parse

executable = pathlib.Path(sys.executable).absolute()
environment = executable.parent.parent
if (environment / "pyvenv.cfg").is_file():
    if os.name == "nt":
        roots = [environment / "Lib" / "site-packages"]
    else:
        roots = [environment / "lib" / ("python%d.%d" % sys.version_info[:2]) / "site-packages"]
    prefix = environment
else:
    configured = sysconfig.get_paths()
    roots = [pathlib.Path(configured["purelib"]), pathlib.Path(configured["platlib"])]
    prefix = pathlib.Path(sys.prefix).resolve()
roots = tuple(dict.fromkeys(path.resolve() for path in roots))
for root in reversed(roots):
    sys.path.insert(0, str(root))

def canonical_name(value):
    return re.sub(r"[-_.]+", "-", str(value or "")).lower()

def exact_distribution(name):
    matches = [
        distribution
        for distribution in md.distributions(path=[str(root) for root in roots])
        if canonical_name(distribution.metadata.get("Name")) == canonical_name(name)
    ]
    if len(matches) != 1:
        raise RuntimeError("selected interpreter has ambiguous distribution metadata")
    return matches[0]

ad = exact_distribution("dcc-mcp-substance3d-designer")
co = exact_distribution("dcc-mcp-core")
se = exact_distribution("dcc-mcp-server")

protected_packages = {
    "dcc_mcp_substance3d_designer",
    "dcc_mcp_core",
    "dcc_mcp_server",
}
for distribution, package in (
    (ad, "dcc_mcp_substance3d_designer"),
    (co, "dcc_mcp_core"),
    (se, "dcc_mcp_server"),
):
    direct_text = distribution.read_text("direct_url.json")
    if not direct_text:
        continue
    direct = json.loads(direct_text)
    url = direct.get("url") if isinstance(direct, dict) else None
    directory = direct.get("dir_info") if isinstance(direct, dict) else None
    if not isinstance(directory, dict) or directory.get("editable") is not True or not isinstance(url, str):
        continue
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
        raise RuntimeError("selected interpreter has an invalid editable distribution origin")
    raw = urllib.parse.unquote(parsed.path)
    if re.fullmatch(r"/[A-Za-z]:/.*", raw):
        raw = raw[1:]
    editable = pathlib.Path(raw).resolve()
    candidates = [editable / "src", editable]
    import_roots = [candidate for candidate in candidates if (candidate / package / "__init__.py").is_file()]
    if len(import_roots) != 1 or editable.is_symlink():
        raise RuntimeError("selected interpreter has an invalid editable distribution origin")
    import_root = import_roots[0]
    if any((import_root / other).exists() for other in protected_packages if other != package):
        raise RuntimeError("editable distribution shadows another protected package")
    sys.path.insert(0, str(import_root))

import dcc_mcp_core
import dcc_mcp_substance3d_designer as adapter
import dcc_mcp_server

def owner(distribution, target):
    for item in tuple(distribution.files or ()):
        if pathlib.Path(distribution.locate_file(item)).resolve() != target:
            continue
        digest = None if item.hash is None else item.hash.mode + "=" + item.hash.value
        return str(item), digest, item.size
    return None, None, None

ap = str(pathlib.Path(adapter.__file__).resolve())
cp = str(pathlib.Path(dcc_mcp_core.__file__).resolve())
sp = str(pathlib.Path(dcc_mcp_server.__file__).resolve())
ar, ah, az = owner(ad, pathlib.Path(ap))
cr, ch, cz = owner(co, pathlib.Path(cp))
sr, sh, sz = owner(se, pathlib.Path(sp))
binary_name = "dcc-mcp-server.exe" if os.name == "nt" else "dcc-mcp-server"
binary_entries = [item for item in tuple(se.files or ()) if pathlib.Path(str(item)).name == binary_name]
if len(binary_entries) != 1:
    raise RuntimeError("selected interpreter has ambiguous Core server binary ownership")
sb = str(pathlib.Path(se.locate_file(binary_entries[0])).resolve())
br, bh, bz = owner(se, pathlib.Path(sb))
au = ad.read_text("direct_url.json")
cu = co.read_text("direct_url.json")
su = se.read_text("direct_url.json")
print(json.dumps({
    "python_version": ".".join(map(str, sys.version_info[:3])),
    "python_root": str(roots[0]),
    "python_platlib": str(roots[-1]),
    "python_prefix": str(prefix),
    "executable": sys.executable,
    "core_version": dcc_mcp_core.__version__,
    "core_dist_version": co.version,
    "server_version": dcc_mcp_server.__version__,
    "server_dist_version": se.version,
    "adapter_version": adapter.__version__,
    "adapter_dist_version": ad.version,
    "adapter_file": ap,
    "core_file": cp,
    "server_file": sp,
    "server_binary": sb,
    "adapter_dist_root": str(pathlib.Path(ad.locate_file("")).resolve()),
    "core_dist_root": str(pathlib.Path(co.locate_file("")).resolve()),
    "server_dist_root": str(pathlib.Path(se.locate_file("")).resolve()),
    "adapter_record": ar,
    "core_record": cr,
    "server_record": sr,
    "server_binary_record": br,
    "adapter_record_hash": ah,
    "core_record_hash": ch,
    "server_record_hash": sh,
    "server_binary_record_hash": bh,
    "adapter_record_size": az,
    "core_record_size": cz,
    "server_record_size": sz,
    "server_binary_record_size": bz,
    "adapter_direct_url": json.loads(au) if au else None,
    "core_direct_url": json.loads(cu) if cu else None,
    "server_direct_url": json.loads(su) if su else None,
}))
""".strip()
    allowed_environment = (
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    )
    probe_env = {key: os.environ[key] for key in allowed_environment if key in os.environ}
    probe_env["PYTHONNOUSERSITE"] = "1"
    probe_env["PYTHONSAFEPATH"] = "1"
    completed = _run_bounded_command(
        [str(python_path), "-I", "-S", "-c", script], timeout=20.0, env=probe_env, private_cwd=True
    )
    if not completed.get("success") or completed.get("truncated"):
        reason = str(completed.get("reason") or "probe failed")
        public_reason = "probe timed out" if reason == "probe timed out" else "probe failed"
        raise LifecycleFailure("python", f"Target interpreter import check {public_reason}.")
    try:
        result = json.loads(str(completed.get("stdout") or "").strip().splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise LifecycleFailure("python", "Target interpreter returned invalid metadata.") from exc
    if not isinstance(result, dict):
        raise LifecycleFailure("python", "Target interpreter returned invalid metadata.")
    reported_executable = Path(str(result.get("executable") or ""))
    if not reported_executable.is_file() or not _same_path(reported_executable, python_path):
        raise LifecycleFailure("python", "Target interpreter identity does not match --python.")
    adapter_version = version_tuple(result.get("adapter_version"))
    adapter_distribution_version = version_tuple(result.get("adapter_dist_version"))
    if (
        adapter_version is None
        or adapter_distribution_version is None
        or result.get("adapter_version") != __version__
        or result.get("adapter_version") != result.get("adapter_dist_version")
    ):
        raise LifecycleFailure("python", "Imported adapter version does not match its installed distribution.")
    core_version = version_tuple(result.get("core_version"))
    core_distribution_version = version_tuple(result.get("core_dist_version"))
    core_floor = version_tuple(MIN_CORE_VERSION)
    if core_version is None or core_distribution_version is None or core_floor is None:
        raise LifecycleFailure("core_version", "dcc-mcp-core returned a noncanonical final version.")
    if result.get("core_version") != result.get("core_dist_version"):
        raise LifecycleFailure("python", "Imported Core version does not match its installed distribution.")
    if core_version < core_floor:
        raise LifecycleFailure("core_version", f"dcc-mcp-core>={MIN_CORE_VERSION} is required.")
    server_version = version_tuple(result.get("server_version"))
    server_distribution_version = version_tuple(result.get("server_dist_version"))
    if (
        server_version is None
        or server_distribution_version is None
        or server_version < core_floor
        or result.get("server_version") != result.get("server_dist_version")
    ):
        raise LifecycleFailure("python", "Imported Core server does not match its installed distribution.")
    python_version = version_tuple(result.get("python_version"))
    if python_version is None or python_version < (3, 9, 0):
        raise LifecycleFailure("python_version", "Python 3.9 or newer is required.")
    trusted_roots = []
    for value in (result.get("python_root"), result.get("python_platlib")):
        root = Path(str(value or ""))
        if not root.is_dir() or _is_link_or_junction(root):
            raise LifecycleFailure("python", "Selected interpreter site-packages is unavailable.")
        if not any(_same_path(root, existing) for existing in trusted_roots):
            trusted_roots.append(root.resolve())
    adapter_file = _require_regular_file(
        Path(str(result.get("adapter_file") or "")), "python", "Imported Designer adapter module"
    )
    core_file = _require_regular_file(Path(str(result.get("core_file") or "")), "python", "Imported Core module")
    server_file = _require_regular_file(
        Path(str(result.get("server_file") or "")), "python", "Imported Core server module"
    )
    _require_distribution_origin(
        adapter_file,
        result.get("adapter_dist_root"),
        result.get("adapter_record"),
        result.get("adapter_record_hash"),
        result.get("adapter_record_size"),
        result.get("adapter_direct_url"),
        trusted_roots,
        distribution="adapter",
        package="dcc_mcp_substance3d_designer",
    )
    _require_distribution_origin(
        core_file,
        result.get("core_dist_root"),
        result.get("core_record"),
        result.get("core_record_hash"),
        result.get("core_record_size"),
        result.get("core_direct_url"),
        trusted_roots,
        distribution="Core",
        package="dcc_mcp_core",
    )
    _require_distribution_origin(
        server_file,
        result.get("server_dist_root"),
        result.get("server_record"),
        result.get("server_record_hash"),
        result.get("server_record_size"),
        result.get("server_direct_url"),
        trusted_roots,
        distribution="Core server",
        package="dcc_mcp_server",
    )
    server_binary = _require_regular_file(
        Path(str(result.get("server_binary") or "")), "python", "Imported Core server binary"
    )
    python_prefix = Path(str(result.get("python_prefix") or ""))
    if not python_prefix.is_dir() or not _path_within(server_binary, python_prefix):
        raise LifecycleFailure("python", "Imported Core server binary is outside the selected interpreter.")
    _require_distribution_artifact(
        server_binary,
        result.get("server_dist_root"),
        result.get("server_binary_record"),
        result.get("server_binary_record_hash"),
        result.get("server_binary_record_size"),
        distribution="Core server",
    )
    return {str(key): "" if value is None else str(value) for key, value in result.items()}


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
        if candidate.name.lower() not in _HOST_EXECUTABLES:
            raise LifecycleFailure("host", "--dcc-path must select the exact Designer executable.")
        selected = _require_regular_file(candidate, "host", "Selected Designer executable")
        if not _host_product_identity(selected):
            raise LifecycleFailure("host", "Selected executable has no verified Adobe Designer product identity.")
        return selected
    candidates = _host_candidates(environ)
    if len(candidates) == 1:
        if not _host_product_identity(candidates[0]):
            raise LifecycleFailure("host", "Discovered executable has no verified Adobe Designer product identity.")
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
        parts = (info.product_version_ms >> 16, info.product_version_ms & 0xFFFF, info.product_version_ls >> 16)
        version = ".".join(str(part) for part in parts)
        return version if version_tuple(version) is not None else None
    except (AttributeError, OSError, ValueError):
        return None


def _windows_version_string(path: Path, field: str) -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        version = ctypes.windll.version
        version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = [
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.UINT),
        ]
        version.VerQueryValueW.restype = wintypes.BOOL
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, data):
            return None
        translation = ctypes.c_void_p()
        translation_length = wintypes.UINT()
        if (
            not version.VerQueryValueW(
                data,
                "\\VarFileInfo\\Translation",
                ctypes.byref(translation),
                ctypes.byref(translation_length),
            )
            or translation_length.value < 4
        ):
            return None
        language, codepage = ctypes.cast(translation, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        value = ctypes.c_void_p()
        value_length = wintypes.UINT()
        query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{field}"
        if not version.VerQueryValueW(data, query, ctypes.byref(value), ctypes.byref(value_length)):
            return None
        if not value.value or value_length.value <= 1:
            return None
        return ctypes.wstring_at(value.value, value_length.value - 1).strip()
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _host_product_identity(path: Path) -> bool:
    """Require platform-owned Adobe Substance 3D Designer identity."""
    if os.name == "nt":
        company = (_windows_version_string(path, "CompanyName") or "").casefold()
        product = (_windows_version_string(path, "ProductName") or "").casefold()
        return "adobe" in company and "substance" in product and "designer" in product
    if sys.platform == "darwin":
        if path.parent.name != "MacOS" or path.parent.parent.name != "Contents":
            return False
        try:
            plist = plistlib.loads((path.parent.parent / "Info.plist").read_bytes())
        except (OSError, ValueError):
            return False
        bundle_id = str(plist.get("CFBundleIdentifier") or "").casefold()
        product = str(plist.get("CFBundleName") or plist.get("CFBundleDisplayName") or "").casefold()
        return "adobe" in bundle_id and "substance" in bundle_id and "designer" in product
    try:
        relative = path.resolve(strict=True).relative_to(Path("/opt/Adobe/Adobe Substance 3D Designer"))
        with path.open("rb") as stream:
            magic = stream.read(4)
    except (OSError, ValueError):
        return False
    return bool(relative.parts) and magic == b"\x7fELF"


def _detect_host_version(path: Path, environ: Mapping[str, str]) -> Tuple[str, str]:
    file_version = _windows_file_version(path)
    if file_version:
        return file_version, "file_metadata"
    if path.parent.name == "MacOS" and path.parent.parent.name == "Contents":
        try:
            metadata = plistlib.loads((path.parent.parent / "Info.plist").read_bytes())
            version = str(metadata.get("CFBundleShortVersionString") or metadata.get("CFBundleVersion") or "").strip()
        except (OSError, ValueError):
            version = ""
        if version_tuple(version) is not None:
            return version, "app_bundle"
    for parent in tuple(path.parents)[:5]:
        match = re.fullmatch(
            r"Adobe Substance 3D Designer (?P<version>(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2})",
            parent.name,
        )
        if match and version_tuple(match.group("version")) is not None:
            return match.group("version"), "path"
    override = str(environ.get(VERSION_ENV) or "")
    if override:
        if version_tuple(override) is None:
            raise LifecycleFailure("host_version", "Designer version override is not a canonical final version.")
        return override, "environment"
    return "", "unavailable"


def _detect_embedded_python_version(path: Path, host_version: str) -> Tuple[str, str]:
    roots = [path.parent / "plugins" / "pythonsdk"]
    if path.parent.name == "MacOS" and path.parent.parent.name == "Contents":
        roots.insert(0, path.parent.parent / "plugins" / "pythonsdk")
    discovered = set()
    for root in roots:
        for marker in root.glob("python*.dll"):
            match = re.fullmatch(r"python(\d)([0-9]{1,2})", marker.stem, re.IGNORECASE)
            if marker.is_file() and match:
                discovered.add(f"{int(match.group(1))}.{int(match.group(2))}")
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
    parsed_host = version_tuple(host_version)
    if parsed_host is None:
        raise LifecycleFailure("host_version", "Designer version metadata is invalid.")
    return ("3.11", "release_matrix") if parsed_host[0] >= 14 else ("3.9", "release_matrix")


def resolve_context(dcc_path: Optional[str], python_path: Optional[str], environ: Mapping[str, str]) -> InstallContext:
    host = _resolve_host_path(dcc_path, environ)
    host_version, host_version_source = _detect_host_version(host, environ)
    parsed_host_version = version_tuple(host_version)
    if parsed_host_version is None or parsed_host_version[:2] < MIN_DESIGNER_VERSION:
        raise LifecycleFailure("host_version", "Designer 12.1 or newer is required and must be identifiable.")
    embedded_python_version, embedded_python_version_source = _detect_embedded_python_version(host, host_version)
    selected_python = python_path or environ.get(PYTHON_ENV) or sys.executable
    interpreter = Path(selected_python).expanduser().absolute()
    if not interpreter.is_file():
        raise LifecycleFailure("python", "Target interpreter does not exist.")
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
        intact = isinstance(files, list) and len(files) == 2
        for item in files if isinstance(files, list) else []:
            if not isinstance(item, dict):
                intact = False
                break
            path = Path(str(item.get("path", "")))
            if not path.is_file() or hash_file(path) != item.get("sha256"):
                intact = False
                break
        state = "upgrade" if receipt.get("adapter_version") != __version__ else ("current" if intact else "repair")
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
        adapter_module_path=Path(python["adapter_file"]).resolve(),
        core_module_path=Path(python["core_file"]).resolve(),
        adapter_distribution_root=Path(python["adapter_dist_root"]).resolve(),
        core_distribution_root=Path(python["core_dist_root"]).resolve(),
        python_prefix=Path(python["python_prefix"]).resolve(),
        server_module_path=Path(python["server_file"]).resolve(),
        server_distribution_root=Path(python["server_dist_root"]).resolve(),
        server_binary_path=Path(python["server_binary"]).resolve(),
    )


__all__ = ["query_python", "resolve_context", "version_tuple"]
