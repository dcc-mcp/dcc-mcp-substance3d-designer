from pathlib import Path

import pytest

from dcc_mcp_substance3d_designer import _install_preflight


def test_windows_python_dll_identifies_embedded_abi(tmp_path: Path):
    host = tmp_path / "host.exe"
    sdk = tmp_path / "plugins/pythonsdk"
    sdk.mkdir(parents=True)
    (sdk / "python313.dll").write_bytes(b"sdk")
    (sdk / "python3.dll").write_bytes(b"stable abi")
    assert _install_preflight._detect_embedded_python_version(host, "16.0.0") == ("3.13", "installation")


def test_windows_conflicting_python_dlls_fail_closed(tmp_path: Path):
    host = tmp_path / "host.exe"
    sdk = tmp_path / "plugins/pythonsdk"
    sdk.mkdir(parents=True)
    for version in ("311", "313"):
        (sdk / f"python{version}.dll").write_bytes(b"sdk")
    with pytest.raises(_install_preflight.LifecycleFailure):
        _install_preflight._detect_embedded_python_version(host, "16.0.0")
