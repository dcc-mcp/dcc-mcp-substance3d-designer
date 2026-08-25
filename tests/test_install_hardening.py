"""Adversarial regressions for the Designer Install SOP lifecycle."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import venv
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from dcc_mcp_substance3d_designer import _install_preflight, _install_process, _installer
from dcc_mcp_substance3d_designer._install_io import write_json_atomic
from dcc_mcp_substance3d_designer._install_model import InstallContext, LifecycleFailure
from dcc_mcp_substance3d_designer.install_cli import main


def _context(tmp_path: Path, *, state: str = "current") -> InstallContext:
    host_root = tmp_path / "Adobe" / "Adobe Substance 3D Designer 15.1.0"
    host = host_root / ("Adobe Substance 3D Designer.exe" if os.name == "nt" else "Adobe Substance 3D Designer")
    host.parent.mkdir(parents=True, exist_ok=True)
    host.write_bytes(b"synthetic-designer-host")
    install_root = tmp_path / "install-root"
    return InstallContext(
        host_path=host.resolve(),
        host_version="15.1.0",
        host_version_source="path",
        embedded_python_version="{}.{}".format(*sys.version_info[:2]),
        embedded_python_version_source="installation",
        python_path=Path(sys.executable).resolve(),
        python_version="{}.{}.{}".format(*sys.version_info[:3]),
        python_root=(tmp_path / "site-packages").resolve(),
        core_version=_installer.MIN_CORE_VERSION,
        install_root=install_root.resolve(),
        receipt_path=install_root / "receipts" / "substance3d_designer.json",
        launcher_path=install_root
        / "launchers"
        / ("substance3d_designer.cmd" if os.name == "nt" else "substance3d_designer.sh"),
        payload_root=install_root / "payload",
        plugin_path=install_root / "payload" / "plugins" / "dcc_mcp_substance3d_designer_plugin.py",
        bootstrap_log_dir=install_root / "logs",
        state=state,
    )


def _write_current_install(ctx: InstallContext) -> dict:
    ctx.plugin_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.launcher_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.plugin_path.write_text("old plugin\n", encoding="utf-8")
    ctx.launcher_path.write_text("old launcher\n", encoding="utf-8")
    receipt = _installer._receipt(ctx, time.time())
    ctx.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return receipt


def test_uses_released_core_contract_and_official_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = root.joinpath("pyproject.toml").read_text(encoding="utf-8").replace(" ", "")
    skill_metadata = [
        path.read_text(encoding="utf-8")
        for path in root.joinpath("src", "dcc_mcp_substance3d_designer", "skills").glob("*/SKILL.md")
    ]
    bundled_plugin = root.joinpath(
        "src",
        "dcc_mcp_substance3d_designer",
        "designer",
        "plugins",
        "dcc_mcp_substance3d_designer_plugin.py",
    ).read_text(encoding="utf-8")

    assert _installer.MIN_CORE_VERSION == "0.20.15"
    assert "dcc-mcp-core>=0.20.15,<1.0.0" in pyproject
    assert skill_metadata and all("dcc-mcp-core 0.20.15+" in metadata for metadata in skill_metadata)
    assert '"min_core_version": "0.20.15"' in bundled_plugin
    assert not root.joinpath("src", "dcc_mcp_substance3d_designer", "_install_contract.py").exists()

    from dcc_mcp_core.deployment import load_install_sop_schema

    Draft202012Validator.check_schema(load_install_sop_schema())


@pytest.mark.parametrize(
    "value",
    ["garbage15.1.0suffix", " 15.1.0 ", "15.1", "15.1.0.2", "015.1.0", "9" * 5000 + ".1.0"],
)
def test_versions_reject_noncanonical_or_unbounded_values(value: str) -> None:
    assert _install_preflight.version_tuple(value) is None


def test_host_version_override_is_last_resort_and_canonical(tmp_path: Path) -> None:
    host = tmp_path / "vendor-build" / "Adobe Substance 3D Designer.exe"
    host.parent.mkdir(parents=True)
    host.write_bytes(b"synthetic")

    assert _install_preflight._detect_host_version(host, {"DCC_MCP_SUBSTANCE3D_DESIGNER_VERSION": "15.1.0"}) == (
        "15.1.0",
        "environment",
    )
    with pytest.raises(LifecycleFailure, match="canonical final version"):
        _install_preflight._detect_host_version(host, {"DCC_MCP_SUBSTANCE3D_DESIGNER_VERSION": "15.1.0-preview+secret"})


def test_explicit_host_rejects_an_arbitrary_executable(tmp_path: Path) -> None:
    impostor = tmp_path / "not-designer.exe"
    impostor.write_bytes(b"not Designer")

    with pytest.raises(LifecycleFailure, match="Designer executable"):
        _install_preflight._resolve_host_path(str(impostor), {})


def test_exact_named_placeholder_is_not_a_designer_product(tmp_path: Path) -> None:
    impostor = tmp_path / "Adobe Substance 3D Designer 15.1.0" / "Adobe Substance 3D Designer.exe"
    impostor.parent.mkdir(parents=True)
    impostor.write_bytes(b"renamed placeholder")

    with pytest.raises(LifecycleFailure, match="product identity"):
        _install_preflight._resolve_host_path(str(impostor), {})


def test_python_probe_rejects_self_consistent_distribution_outside_selected_purelib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hostile = tmp_path / "hostile"
    adapter_file = hostile / "dcc_mcp_substance3d_designer" / "__init__.py"
    core_file = hostile / "dcc_mcp_core" / "__init__.py"
    for path in (adapter_file, core_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# hostile\n", encoding="utf-8")
    payload = {
        "python_version": "{}.{}.{}".format(*sys.version_info[:3]),
        "python_root": str((tmp_path / "real-site-packages").resolve()),
        "python_platlib": str((tmp_path / "real-site-packages").resolve()),
        "executable": str(Path(sys.executable).resolve()),
        "core_version": _installer.MIN_CORE_VERSION,
        "core_dist_version": _installer.MIN_CORE_VERSION,
        "adapter_version": _installer.__version__,
        "adapter_dist_version": _installer.__version__,
        "adapter_file": str(adapter_file),
        "core_file": str(core_file),
        "adapter_dist_root": str(hostile.resolve()),
        "core_dist_root": str(hostile.resolve()),
        "adapter_record": "dcc_mcp_substance3d_designer/__init__.py",
        "core_record": "dcc_mcp_core/__init__.py",
        "adapter_record_hash": None,
        "core_record_hash": None,
        "adapter_record_size": adapter_file.stat().st_size,
        "core_record_size": core_file.stat().st_size,
        "adapter_direct_url": None,
        "core_direct_url": None,
    }
    completed = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: completed)
    monkeypatch.setattr(
        _install_preflight,
        "_run_bounded_command",
        lambda *_args, **_kwargs: {"success": True, "stdout": json.dumps(payload), "stderr": ""},
        raising=False,
    )

    with pytest.raises(LifecycleFailure, match="distribution|site-packages|shadow"):
        _install_preflight.query_python(Path(sys.executable).resolve())


def _write_minimal_distribution(site: Path, distribution: str, package: str, version: str) -> None:
    module = site / package / "__init__.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text('__version__ = "{}"\n'.format(version), encoding="utf-8")
    digest = base64.urlsafe_b64encode(hashlib.sha256(module.read_bytes()).digest()).rstrip(b"=").decode("ascii")
    dist_info = site / "{}-{}.dist-info".format(distribution.replace("-", "_"), version)
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: {}\nVersion: {}\n".format(distribution, version), encoding="utf-8"
    )
    (dist_info / "RECORD").write_text(
        "{}/__init__.py,sha256={},{}\n".format(package, digest, module.stat().st_size), encoding="utf-8"
    )


def _write_minimal_server_distribution(site: Path, environment: Path, version: str) -> None:
    binary = environment / ("Scripts/dcc-mcp-server.exe" if os.name == "nt" else "bin/dcc-mcp-server")
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"official-server-binary")
    module = site / "dcc_mcp_server" / "__init__.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(
        "__version__ = {!r}\ndef binary_path(): raise RuntimeError('locator must not be called')\n".format(version),
        encoding="utf-8",
    )
    dist_info = site / "dcc_mcp_server-{}.dist-info".format(version)
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: dcc-mcp-server\nVersion: {}\n".format(version), encoding="utf-8"
    )
    records = []
    for path in (module, binary):
        digest = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b"=").decode("ascii")
        records.append(
            "{},sha256={},{}".format(Path(os.path.relpath(path, site)).as_posix(), digest, path.stat().st_size)
        )
    (dist_info / "RECORD").write_text("\n".join(records) + "\n", encoding="utf-8")


def test_python_probe_does_not_execute_target_sitecustomize(tmp_path: Path) -> None:
    environment = tmp_path / "target"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = (
        environment / "Lib" / "site-packages"
        if os.name == "nt"
        else environment / "lib" / "python{}.{}".format(*sys.version_info[:2]) / "site-packages"
    )
    marker = tmp_path / "sitecustomize-ran"
    intended = (environment, python, site, marker)
    private_root = str(tmp_path.resolve())
    assert all(os.path.commonpath((private_root, str(path.resolve()))) == private_root for path in intended)

    venv.EnvBuilder(with_pip=False).create(environment)
    site.mkdir(parents=True, exist_ok=True)
    _write_minimal_distribution(
        site, "dcc-mcp-substance3d-designer", "dcc_mcp_substance3d_designer", _installer.__version__
    )
    _write_minimal_distribution(site, "dcc-mcp-core", "dcc_mcp_core", _installer.MIN_CORE_VERSION)
    _write_minimal_server_distribution(site, environment, _installer.MIN_CORE_VERSION)
    (site / "sitecustomize.py").write_text(
        "from pathlib import Path\nPath({!r}).write_text('ran', encoding='utf-8')\n".format(str(marker)),
        encoding="utf-8",
    )

    result = _install_preflight.query_python(python.absolute())

    assert result["core_version"] == _installer.MIN_CORE_VERSION
    assert not marker.exists()


def test_distribution_record_digest_must_match_imported_module(tmp_path: Path) -> None:
    trusted = tmp_path / "site-packages"
    module = trusted / "dcc_mcp_core" / "__init__.py"
    module.parent.mkdir(parents=True)
    module.write_text("__version__ = '0.20.15'\n", encoding="utf-8")
    original = module.read_bytes()
    digest = base64.urlsafe_b64encode(hashlib.sha256(original).digest()).rstrip(b"=").decode("ascii")
    module.write_text("__version__ = 'changed'\n", encoding="utf-8")

    with pytest.raises(LifecycleFailure, match="RECORD integrity"):
        _install_preflight._require_distribution_origin(
            module,
            trusted,
            "dcc_mcp_core/__init__.py",
            f"sha256={digest}",
            len(original),
            None,
            [trusted],
            distribution="Core",
            package="dcc_mcp_core",
        )


def test_core_server_binary_must_match_its_distribution_record(tmp_path: Path) -> None:
    trusted = tmp_path / "environment" / "Lib" / "site-packages"
    binary = tmp_path / "environment" / "Scripts" / "dcc-mcp-server.exe"
    trusted.mkdir(parents=True)
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"official-server")
    original = binary.read_bytes()
    digest = base64.urlsafe_b64encode(hashlib.sha256(original).digest()).rstrip(b"=").decode("ascii")
    record = Path(os.path.relpath(binary, trusted)).as_posix()
    binary.write_bytes(b"replaced-server")

    with pytest.raises(LifecycleFailure, match="RECORD integrity"):
        _install_preflight._require_distribution_artifact(
            binary,
            trusted,
            record,
            f"sha256={digest}",
            len(original),
            distribution="Core server",
        )


def test_receipt_atomic_replace_failure_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "receipts" / "substance3d_designer.json"

    def fail_replace(*_args, **_kwargs):
        raise PermissionError("synthetic lock")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        write_json_atomic(receipt, {"schema_version": 1})

    assert not receipt.exists()
    assert not list(receipt.parent.glob("*.tmp"))


def test_receipt_temporary_cleanup_failure_is_operator_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = tmp_path / "receipts" / "substance3d_designer.json"
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(PermissionError("replace failed")))
    original_unlink = Path.unlink

    def fail_temporary_cleanup(path: Path, *args, **kwargs):
        if path.name.startswith(f".{receipt.name}."):
            raise PermissionError("cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_temporary_cleanup)
    with pytest.raises(LifecycleFailure) as raised:
        write_json_atomic(receipt, {"schema_version": 1})

    assert raised.value.stage == "cleanup"


def test_process_cleanup_fails_closed_when_tree_does_not_become_empty() -> None:
    process = SimpleNamespace(poll=lambda: None, kill=lambda: None, wait=lambda timeout: 0)
    owner = SimpleNamespace(
        terminate=lambda: None,
        wait_empty=lambda timeout: False,
        close=lambda: None,
    )

    assert _install_process._cleanup_owned_process(process, owner) is False


def test_darwin_process_identity_distinguishes_same_second_microsecond_reuse() -> None:
    assert ctypes.sizeof(_install_process._DarwinProcBsdInfo) == 136
    observations = iter((123_456, 123_457))

    def fake_proc_pidinfo(pid, flavor, arg, buffer, size):
        assert pid == 9123
        assert flavor == _install_process._PROC_PIDTBSDINFO
        assert arg == 0
        info = _install_process._DarwinProcBsdInfo()
        info.pbi_pid = pid
        info.pbi_ppid = 42
        info.pbi_start_tvsec = 1_777_000_000
        info.pbi_start_tvusec = next(observations)
        assert size == ctypes.sizeof(info)
        ctypes.memmove(buffer, ctypes.byref(info), size)
        return size

    first = _install_process._read_darwin_bsd_identity(9123, fake_proc_pidinfo)
    second = _install_process._read_darwin_bsd_identity(9123, fake_proc_pidinfo)

    assert first == {
        "parent_pid": 42,
        "start_identity": "darwin-proc-bsdinfo:1777000000:123456",
    }
    assert second == {
        "parent_pid": 42,
        "start_identity": "darwin-proc-bsdinfo:1777000000:123457",
    }
    assert first != second


def test_darwin_observation_uses_libproc_without_platform_local_shadowing(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeFunction:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    def fake_proc_pidpath(pid, buffer, size):
        assert pid == 9123
        payload = b"/usr/bin/python3\0"
        assert len(payload) <= size
        ctypes.memmove(buffer, payload, len(payload))
        return len(payload) - 1

    def fake_proc_pidinfo(pid, flavor, arg, buffer, size):
        assert flavor == _install_process._PROC_PIDTBSDINFO
        assert arg == 0
        info = _install_process._DarwinProcBsdInfo()
        info.pbi_pid = pid
        info.pbi_ppid = 42
        info.pbi_start_tvsec = 1_777_000_000
        info.pbi_start_tvusec = 123_456
        ctypes.memmove(buffer, ctypes.byref(info), size)
        return size

    fake_libproc = SimpleNamespace(
        proc_pidpath=FakeFunction(fake_proc_pidpath),
        proc_pidinfo=FakeFunction(fake_proc_pidinfo),
    )
    monkeypatch.setattr(_install_process.sys, "platform", "darwin")
    monkeypatch.setattr(_install_process.ctypes, "CDLL", lambda *_args, **_kwargs: fake_libproc)

    identity = _install_process.observe_process_identity(9123)

    assert identity is not None
    assert identity["pid"] == 9123
    assert identity["parent_pid"] == 42
    assert identity["start_identity"] == "darwin-proc-bsdinfo:1777000000:123456"


@pytest.mark.parametrize(
    ("returned_size", "observed_pid", "parent_pid", "seconds", "microseconds"),
    [
        (0, 9123, 42, 1_777_000_000, 123_456),
        (None, 9999, 42, 1_777_000_000, 123_456),
        (None, 9123, 0, 1_777_000_000, 123_456),
        (None, 9123, 42, 0, 123_456),
        (None, 9123, 42, 1_777_000_000, 1_000_000),
    ],
)
def test_darwin_process_identity_fails_closed_on_invalid_kernel_record(
    returned_size: int | None,
    observed_pid: int,
    parent_pid: int,
    seconds: int,
    microseconds: int,
) -> None:
    def fake_proc_pidinfo(pid, _flavor, _arg, buffer, size):
        info = _install_process._DarwinProcBsdInfo()
        info.pbi_pid = observed_pid
        info.pbi_ppid = parent_pid
        info.pbi_start_tvsec = seconds
        info.pbi_start_tvusec = microseconds
        ctypes.memmove(buffer, ctypes.byref(info), size)
        return size if returned_size is None else returned_size

    assert _install_process._read_darwin_bsd_identity(9123, fake_proc_pidinfo) is None


def test_posix_owner_wait_empty_rejects_a_surviving_group_member(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(_install_process._PosixProcessTreeOwner)
    owner._process = SimpleNamespace(wait=lambda timeout: 0)
    owner._pgid = 9123
    monkeypatch.setattr(_install_process, "_list_posix_process_group_members", lambda _pgid: {9912})

    assert owner.wait_empty(0.0) is False


def test_posix_group_snapshot_accepts_bsd_ps_empty_heading(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = SimpleNamespace(returncode=0, stdout="\n  9912  9123\n  9913  9913\n")
    monkeypatch.setattr(_install_process.subprocess, "run", lambda *_args, **_kwargs: completed)

    assert _install_process._list_posix_process_group_members(9123) == {9912}


def test_listener_observation_binds_an_exact_direct_child_process() -> None:
    script = (
        "import socket,time; "
        "listener=socket.socket(); "
        "listener.bind(('127.0.0.1',0)); "
        "listener.listen(); "
        "print(listener.getsockname()[1],flush=True); "
        "time.sleep(30)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert child.stdout is not None
        port = int(child.stdout.readline().strip())
        observed = _install_process.observe_listener_identity(f"http://127.0.0.1:{port}/mcp")

        assert observed is not None
        assert observed["pid"] == child.pid or observed["parent_pid"] == child.pid
        if observed["pid"] == child.pid:
            assert observed["parent_pid"] == os.getpid()
        assert observed["listener_port"] == port
    finally:
        child.kill()
        child.wait(timeout=3)


def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel32.CloseHandle(handle)


def test_interpreter_probe_timeout_terminates_root_and_descendant(tmp_path: Path) -> None:
    identities = tmp_path / "probe-pids.txt"
    script = (
        "import os,pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"pathlib.Path({str(identities)!r}).write_text(str(os.getpid())+' '+str(child.pid)); "
        "time.sleep(60)"
    )

    outcome = _install_process.run_bounded_command([sys.executable, "-c", script], timeout=5.0)

    assert outcome["success"] is False
    assert outcome["reason"] == "probe timed out"
    assert identities.is_file(), outcome
    root_pid, descendant_pid = (int(value) for value in identities.read_text(encoding="utf-8").split())
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and (_pid_alive(root_pid) or _pid_alive(descendant_pid)):
        time.sleep(0.05)
    assert not _pid_alive(root_pid)
    assert not _pid_alive(descendant_pid)


def test_owned_supervisor_cleans_replacement_after_command_root_exits(tmp_path: Path) -> None:
    """The durable owner outlives a root that hands work to a replacement child."""
    ready = tmp_path / "replacement.json"
    release = tmp_path / "release-root"
    supervisor_root = tmp_path / "supervisor"
    helper_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    script = (
        "import pathlib,subprocess,sys,time; "
        "replacement=subprocess.Popen([sys.executable,'-c',"
        "'import json,os,pathlib,socket,sys,time; '"
        "+'listener=socket.socket(); listener.bind((\"127.0.0.1\",0)); listener.listen(); '"
        '+\'pathlib.Path(sys.argv[1]).write_text(json.dumps({"pid":os.getpid(),"port":listener.getsockname()[1]})); \''
        "+'time.sleep(60)',sys.argv[1]]); "
        "release=pathlib.Path(sys.argv[2]); deadline=time.monotonic()+5; "
        "exec('while not release.exists() and time.monotonic() < deadline:\\n time.sleep(0.01)')"
    )

    process, owner = _install_process._start_owned_supervised_process(
        [str(helper_python), "-c", script, str(ready), str(release)],
        env=os.environ.copy(),
        cwd=tmp_path,
        root=supervisor_root,
    )
    replacement = None
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not ready.is_file():
            time.sleep(0.02)
        assert ready.is_file()
        replacement = json.loads(ready.read_text(encoding="utf-8"))
        root_identity = _install_process.observe_process_identity(process.pid)
        replacement_identity = _install_process.observe_process_identity(replacement["pid"])
        assert root_identity is not None
        assert replacement_identity is not None
        assert root_identity["pid"] == process.pid
        assert root_identity["parent_pid"] == process.supervisor_pid
        assert replacement_identity["parent_pid"] == process.pid
        root_executable = Path(root_identity["executable"]).resolve()
        replacement_executable = Path(replacement_identity["executable"]).resolve()
        assert root_executable.is_file()
        assert replacement_executable == root_executable
        assert root_identity["start_identity"]
        assert replacement_identity["start_identity"]
        assert (
            root_identity["pid"],
            root_executable,
            root_identity["start_identity"],
        ) != (
            replacement_identity["pid"],
            replacement_executable,
            replacement_identity["start_identity"],
        )
        observed = _install_process.observe_listener_identity(f"http://127.0.0.1:{replacement['port']}/mcp")
        assert observed == {**replacement_identity, "listener_port": replacement["port"]}
        release.write_text("exit", encoding="utf-8")
        assert process.wait(timeout=3.0) == 0
        assert _pid_alive(replacement["pid"])
    finally:
        assert _install_process._cleanup_owned_process(process, owner)

    assert replacement is not None
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and _pid_alive(replacement["pid"]):
        time.sleep(0.02)
    assert not _pid_alive(replacement["pid"])
    assert _install_process.observe_listener_identity(f"http://127.0.0.1:{replacement['port']}/mcp") is None


@pytest.mark.skipif(os.name != "posix", reason="POSIX session/process-group contract")
def test_owned_supervisor_cleans_live_tree_when_controller_is_sigkilled(tmp_path: Path) -> None:
    """A killed caller must not strand a still-running supervised process tree."""
    controller_ready = tmp_path / "controller.json"
    descendant_ready = tmp_path / "descendant.json"
    supervisor_root = tmp_path / "supervisor"
    source_root = Path(__file__).resolve().parents[1] / "src"
    helper_python = Path(sys.executable).absolute()
    descendant_code = (
        "import json,os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid()}),encoding='utf-8'); "
        "time.sleep(60)"
    )
    root_code = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(60)"
    )
    controller_code = (
        "import json,os,pathlib,sys,time; "
        "from dcc_mcp_substance3d_designer import _install_process; "
        "process,owner=_install_process._start_owned_supervised_process("
        "[sys.argv[1],'-c',sys.argv[2],sys.argv[3],sys.argv[4]],"
        "env=os.environ.copy(),cwd=pathlib.Path(sys.argv[5]),root=pathlib.Path(sys.argv[6])); "
        "pathlib.Path(sys.argv[7]).write_text(json.dumps("
        "{'pid':os.getpid(),'supervisor_pid':process.supervisor_pid,'root_pid':process.pid}),encoding='utf-8'); "
        "time.sleep(60)"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)
    controller = subprocess.Popen(
        [
            str(helper_python),
            "-c",
            controller_code,
            str(helper_python),
            root_code,
            descendant_code,
            str(descendant_ready),
            str(tmp_path),
            str(supervisor_root),
            str(controller_ready),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        env=environment,
        cwd=tmp_path,
    )
    expected = {}
    try:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and not (controller_ready.is_file() and descendant_ready.is_file()):
            assert controller.poll() is None
            time.sleep(0.02)
        assert controller_ready.is_file()
        assert descendant_ready.is_file()
        tree = json.loads(controller_ready.read_text(encoding="utf-8"))
        descendant = json.loads(descendant_ready.read_text(encoding="utf-8"))
        pids = {
            "controller": int(tree["pid"]),
            "supervisor": int(tree["supervisor_pid"]),
            "root": int(tree["root_pid"]),
            "descendant": int(descendant["pid"]),
        }
        assert pids["controller"] == controller.pid
        expected = {name: _install_process.observe_process_identity(pid) for name, pid in pids.items()}
        assert all(identity is not None for identity in expected.values())
        assert expected["supervisor"]["parent_pid"] == pids["controller"]
        assert expected["root"]["parent_pid"] == pids["supervisor"]
        assert expected["descendant"]["parent_pid"] == pids["root"]

        os.kill(controller.pid, signal.SIGKILL)
        controller.wait(timeout=3.0)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and any(_pid_alive(pid) for pid in pids.values()):
            time.sleep(0.02)
        assert all(not _pid_alive(pid) for pid in pids.values())
    finally:
        if controller.poll() is None:
            controller.kill()
        try:
            controller.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        for name in ("descendant", "root", "supervisor"):
            identity = expected.get(name)
            if identity is None:
                continue
            current = _install_process.observe_process_identity(int(identity["pid"]))
            if current == identity:
                os.kill(int(identity["pid"]), signal.SIGKILL)


def test_probe_temp_cleanup_retries_a_transient_file_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe_root = tmp_path / "probe"
    probe_root.mkdir()
    (probe_root / "stderr.bin").write_bytes(b"probe")
    original = _install_process.shutil.rmtree
    calls = 0

    def transient_lock(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("synthetic transient file lock")
        original(path)

    monkeypatch.setattr(_install_process.shutil, "rmtree", transient_lock)

    assert _install_process._remove_probe_directory(probe_root, timeout=1.0)
    assert calls == 2
    assert not probe_root.exists()


def test_lifecycle_lock_rejects_a_concurrent_install_root_mutation(tmp_path: Path) -> None:
    with _installer._install_lock(tmp_path / "install-root"):
        with pytest.raises(LifecycleFailure, match="already in progress"):
            with _installer._install_lock(tmp_path / "install-root"):
                pass


def test_lifecycle_lock_release_failure_never_reports_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_root = tmp_path / "install-root"
    lock = install_root / "locks" / "substance3d_designer.lock"
    original_unlink = Path.unlink

    def fail_lock_release(path: Path, *args, **kwargs):
        if path == lock:
            raise PermissionError("synthetic stale lock")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock_release)
    with pytest.raises(LifecycleFailure, match="lock release") as raised:
        with _installer._install_lock(install_root):
            pass

    assert raised.value.stage == "cleanup"
    assert lock.is_file()


def test_lifecycle_lock_release_failure_does_not_mask_inflight_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root = tmp_path / "install-root"
    lock = install_root / "locks" / "substance3d_designer.lock"
    original_unlink = Path.unlink

    def fail_lock_release(path: Path, *args, **kwargs):
        if path == lock:
            raise PermissionError("synthetic stale lock")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock_release)
    with pytest.warns(RuntimeWarning, match="lock release"):
        with pytest.raises(RuntimeError, match="primary failure"):
            with _installer._install_lock(install_root):
                raise RuntimeError("primary failure")

    assert lock.is_file()


def test_uninstall_refuses_unreceipted_content_inside_managed_tree(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    _write_current_install(ctx)
    operator_file = ctx.payload_root / "operator-owned.txt"
    operator_file.write_text("keep\n", encoding="utf-8")

    with pytest.raises(LifecycleFailure, match="receipt|owned"):
        _installer._execute_uninstall(ctx)

    assert operator_file.read_text(encoding="utf-8") == "keep\n"
    assert ctx.receipt_path.is_file()


def test_repair_refuses_unreceipted_content_before_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _context(tmp_path, state="repair")
    _write_current_install(ctx)
    ctx.plugin_path.unlink()
    operator_file = ctx.payload_root / "operator-owned.txt"
    operator_file.write_text("keep\n", encoding="utf-8")
    replacements = []
    original_replace = _installer.safe_replace_tree

    def tracked_replace(source, destination):
        replacements.append((source, destination))
        return original_replace(source, destination)

    monkeypatch.setattr(_installer, "safe_replace_tree", tracked_replace)

    with pytest.raises(LifecycleFailure, match="receipt|owned"):
        _installer._execute_install(ctx, {})

    assert replacements == []
    assert operator_file.read_text(encoding="utf-8") == "keep\n"
    assert ctx.receipt_path.is_file()


def test_upgrade_readiness_failure_restores_previous_payload_launcher_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _context(tmp_path)
    _write_current_install(ctx)
    before = {
        ctx.plugin_path: ctx.plugin_path.read_bytes(),
        ctx.launcher_path: ctx.launcher_path.read_bytes(),
        ctx.receipt_path: ctx.receipt_path.read_bytes(),
    }
    monkeypatch.setattr(
        _installer,
        "_verify",
        lambda *_args, **_kwargs: (
            {"directly_usable": False, "failure_stage": "readiness", "failure_reason": "not ready"},
            [],
        ),
    )

    outcome = _installer._execute_install(ctx, {})

    assert outcome.exit_code == 40
    assert outcome.result["previous_restored"] is True
    assert {path: path.read_bytes() for path in before} == before


def test_streamable_fallback_consumes_only_the_remaining_probe_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    from dcc_mcp_substance3d_designer import _install_verify

    clock = [100.0]
    fallback_timeouts = []

    def primary_probe(*_args, **_kwargs):
        clock[0] += 0.75
        return {"status": "probe_http_error", "http_status": 406}

    def streamable_probe(_url, timeout_secs):
        fallback_timeouts.append(timeout_secs)
        return {"success": False, "status": "probe_timeout"}

    monkeypatch.setattr(_install_verify.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(_install_verify, "probe_sidecar_tool", primary_probe)
    monkeypatch.setattr(_install_verify, "_probe_streamable_tool", streamable_probe)

    outcome = _install_verify._probe_runtime_tool("http://127.0.0.1:18812/mcp", 1.0)

    assert outcome["success"] is False
    assert len(fallback_timeouts) == 1
    assert 0.0 < fallback_timeouts[0] <= 0.25


def test_listener_binding_accepts_only_the_host_or_its_direct_owned_server() -> None:
    from dcc_mcp_substance3d_designer import _install_verify

    host_pid = 100
    ctx = SimpleNamespace(
        host_path=Path("designer.exe"),
        server_binary_path=Path("dcc-mcp-server.exe"),
    )
    assert _install_verify._listener_belongs_to_runtime(
        {"pid": host_pid, "parent_pid": 1, "executable": str(ctx.host_path), "start_identity": "host-start"},
        host_pid,
        ctx,
    )
    assert _install_verify._listener_belongs_to_runtime(
        {
            "pid": 101,
            "parent_pid": host_pid,
            "executable": str(ctx.server_binary_path),
            "start_identity": "server-start",
        },
        host_pid,
        ctx,
    )
    assert not _install_verify._listener_belongs_to_runtime(
        {
            "pid": 101,
            "parent_pid": host_pid,
            "executable": "foreign-server.exe",
            "start_identity": "foreign-start",
        },
        host_pid,
        ctx,
    )
    assert not _install_verify._listener_belongs_to_runtime(
        {
            "pid": 101,
            "parent_pid": 99,
            "executable": str(ctx.server_binary_path),
            "start_identity": "server-start",
        },
        host_pid,
        ctx,
    )
    assert not _install_verify._listener_belongs_to_runtime(
        {"pid": 101, "parent_pid": host_pid, "executable": str(ctx.server_binary_path)}, host_pid, ctx
    )


def test_verify_rejects_foreign_runtime_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _context(tmp_path)
    _write_current_install(ctx)
    from dcc_mcp_substance3d_designer import _install_verify

    monkeypatch.setattr(_install_verify, "query_python", lambda _path: {})
    monkeypatch.setattr(
        _install_verify,
        "query_runtime_state",
        lambda *_args, **_kwargs: {
            "entries": [
                {
                    "dcc_type": "substance3d_designer",
                    "mcp_url": "http://127.0.0.1:18812/mcp",
                    "instance_id": "foreign-runtime",
                    "adapter_version": _installer.__version__,
                    "metadata": {"dcc_pid": 123, "dcc_version": ctx.host_version},
                }
            ]
        },
    )
    monkeypatch.setattr(
        _install_verify,
        "_probe_runtime_tool",
        lambda *_args, **_kwargs: {"success": True, "result": {"success": True, "version": ctx.host_version}},
    )
    monkeypatch.setattr(
        _install_verify,
        "_observe_process_identity",
        lambda _pid: {"pid": 123, "executable": str(tmp_path / "foreign.exe"), "start_identity": "foreign"},
        raising=False,
    )

    verify, _next_steps = _install_verify.verify(ctx, {})

    assert verify["directly_usable"] is False
    assert verify["failure_stage"] == "readiness_identity"


def test_invalid_json_cli_arguments_are_schema_valid_and_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["install", "--json", "--unknown-option", "secret-token"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 10
    assert captured.err == ""
    assert result["verify"]["failure_stage"] == "arguments"
    assert "secret-token" not in json.dumps(result)

    from dcc_mcp_core.deployment import load_install_sop_schema

    Draft202012Validator(load_install_sop_schema()).validate(result)


def test_unexpected_failures_are_classified_without_secret_or_path_disclosure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "token-123"
    monkeypatch.setattr(
        _installer,
        "_resolve_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(f"{secret} at C:/private/operator.txt")),
    )

    outcome = _installer.run_lifecycle("install", dcc_path=None, python_path=None, yes=False, dry_run=True, environ={})
    serialized = json.dumps(outcome.result)

    assert outcome.exit_code == 30
    assert secret not in serialized
    assert "private/operator" not in serialized
    assert outcome.result["verify"]["failure_stage"] == "install"
