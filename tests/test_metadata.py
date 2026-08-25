from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import zipfile
from importlib import util
from pathlib import Path

import pytest
import yaml

import dcc_mcp_substance3d_designer as adapter

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "dcc_mcp_substance3d_designer"
PROJECT = "dcc-mcp-substance3d-designer"


def test_release_metadata_is_synchronized():
    manifest = json.loads(ROOT.joinpath(".release-please-manifest.json").read_text(encoding="utf-8"))
    version = re.search(r'(?m)^version = "([^"]+)"$', ROOT.joinpath("pyproject.toml").read_text(encoding="utf-8"))
    assert version is not None
    assert version.group(1) == adapter.__version__ == manifest["."]


def test_plugin_and_skill_contract_files_exist():
    package = ROOT / "src" / "dcc_mcp_substance3d_designer"
    assert package.joinpath("designer_plugin.py").exists()
    assert package.joinpath("skills", "designer-session", "SKILL.md").exists()
    assert package.joinpath("skills", "designer-session", "tools.yaml").exists()


def _skill_files() -> list[Path]:
    return sorted((ROOT / "src" / "dcc_mcp_substance3d_designer" / "skills").glob("*/SKILL.md"))


def test_all_packaged_skill_metadata_matches_the_adapter():
    skill_files = _skill_files()
    assert skill_files

    for skill_file in skill_files:
        frontmatter = skill_file.read_text(encoding="utf-8").split("---", 2)[1]
        metadata = yaml.safe_load(frontmatter)
        assert metadata["metadata"]["dcc-mcp"]["version"] == adapter.__version__, skill_file

    designer_session = next(path for path in skill_files if path.parent.name == "designer-session")
    session_metadata = yaml.safe_load(designer_session.read_text(encoding="utf-8").split("---", 2)[1])
    assert "author" in session_metadata["description"].casefold()


def test_release_please_tracks_every_packaged_skill_version():
    config = json.loads(ROOT.joinpath("release-please-config.json").read_text(encoding="utf-8"))
    configured = {entry["path"] for entry in config["packages"]["."]["extra-files"] if entry.get("type") == "generic"}
    expected = {path.relative_to(ROOT).as_posix() for path in _skill_files()}
    assert expected <= configured


def _workflow_steps(name: str, job: str) -> list[dict[str, object]]:
    workflow = yaml.safe_load(ROOT.joinpath(".github", "workflows", name).read_text(encoding="utf-8"))
    return workflow["jobs"][job]["steps"]


def _run_index(steps: list[dict[str, object]], command: str) -> int:
    return next(index for index, step in enumerate(steps) if step.get("run") == command)


def test_release_validates_source_and_built_wheel_before_publish():
    steps = _workflow_steps("release.yml", "build-and-publish")
    dependencies = _run_index(steps, "python -m pip install --upgrade pip build twine pyyaml")
    source_check = _run_index(steps, "python tools/check_release_metadata.py")
    build = _run_index(steps, "python -m build")
    wheel_check = _run_index(steps, "python tools/check_release_metadata.py --wheel dist/*.whl")
    publish = next(
        index for index, step in enumerate(steps) if step.get("uses") == "pypa/gh-action-pypi-publish@release/v1"
    )
    assert dependencies < source_check < build < wheel_check < publish


def test_ci_validates_the_built_wheel_metadata():
    steps = _workflow_steps("ci.yml", "lint-and-build")
    build = _run_index(steps, "python -m build")
    wheel_check = _run_index(steps, "python tools/check_release_metadata.py --wheel dist/*.whl")
    assert build < wheel_check


def test_release_metadata_checker_accepts_the_repository():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_release_metadata.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def _checker():
    checker_path = ROOT / "tools" / "check_release_metadata.py"
    spec = util.spec_from_file_location("designer_release_metadata_checker", checker_path)
    assert spec is not None and spec.loader is not None
    checker = util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker


def _write_wheel(
    wheel: Path,
    *,
    metadata_name: str = PROJECT,
    dist_info: str = f"{PACKAGE}-0.6.0.dist-info",
    mutate_skill=None,
) -> None:
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(dist_info + "/METADATA", f"Name: {metadata_name}\nVersion: {adapter.__version__}\n")
        archive.writestr(f"{PACKAGE}/__version__.py", f'__version__ = "{adapter.__version__}"\n')
        for skill_file in _skill_files():
            skill_text = skill_file.read_text(encoding="utf-8")
            if mutate_skill is not None:
                skill_text = mutate_skill(skill_file.parent.name, skill_text)
            archive.writestr(f"{PACKAGE}/skills/{skill_file.parent.name}/SKILL.md", skill_text)


def _copy_release_metadata_tree(tmp_path: Path) -> Path:
    for name in ("pyproject.toml", ".release-please-manifest.json", "release-please-config.json"):
        shutil.copy2(ROOT / name, tmp_path / name)
    package = tmp_path / "src" / PACKAGE
    package.mkdir(parents=True)
    shutil.copy2(ROOT / "src" / PACKAGE / "__version__.py", package / "__version__.py")
    shutil.copytree(ROOT / "src" / PACKAGE / "skills", package / "skills")
    return tmp_path


def test_release_metadata_checker_rejects_a_stale_wheel_skill(tmp_path: Path):
    checker = _checker()

    wheel = tmp_path / f"{PACKAGE}-0.6.0-py3-none-any.whl"
    _write_wheel(
        wheel,
        mutate_skill=lambda name, text: (
            text.replace(adapter.__version__, "0.5.0", 1) if name == "designer-diagnostics" else text
        ),
    )

    with pytest.raises(checker.MetadataError, match="does not match source"):
        checker.validate_wheel(ROOT, wheel, adapter.__version__)


def test_release_metadata_checker_rejects_the_wrong_distribution(tmp_path: Path):
    checker = _checker()
    wheel = tmp_path / "not_designer-9.9.9-py3-none-any.whl"
    _write_wheel(wheel, metadata_name="not-designer", dist_info="not_designer-9.9.9.dist-info")

    with pytest.raises(checker.MetadataError, match="distribution"):
        checker.validate_wheel(ROOT, wheel, adapter.__version__)


@pytest.mark.parametrize(
    "mutate_skill",
    [
        lambda name, text: text.replace("\n---\n", "\nbroken: [\n---\n", 1) if name == "designer-diagnostics" else text,
        lambda name, text: (
            re.sub(
                r'(?m)^    version: "[^"]+".*$',
                f'other:\n  version: "{adapter.__version__}" # x-release-please-version',
                text,
            )
            if name == "designer-diagnostics"
            else text
        ),
    ],
)
def test_release_metadata_checker_binds_the_real_skill_yaml_path(tmp_path: Path, mutate_skill):
    checker = _checker()
    wheel = tmp_path / f"{PACKAGE}-0.6.0-py3-none-any.whl"
    _write_wheel(wheel, mutate_skill=mutate_skill)

    with pytest.raises(checker.MetadataError, match="Skill metadata"):
        checker.validate_wheel(ROOT, wheel, adapter.__version__)


def test_release_metadata_checker_rejects_malformed_source_yaml(tmp_path: Path):
    checker = _checker()
    root = _copy_release_metadata_tree(tmp_path)
    skill = root / "src" / PACKAGE / "skills" / "designer-diagnostics" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("\n---\n", "\nbroken: [\n---\n", 1), encoding="utf-8")

    with pytest.raises(checker.MetadataError, match="Skill metadata"):
        checker.validate_source(root)


def test_release_metadata_checker_rejects_duplicate_manifest_keys(tmp_path: Path):
    checker = _checker()
    root = _copy_release_metadata_tree(tmp_path)
    root.joinpath(".release-please-manifest.json").write_text('{".":"9.9.9",".":"0.6.0"}\n', encoding="utf-8")

    with pytest.raises(checker.MetadataError, match="duplicate JSON key"):
        checker.validate_source(root)


def test_release_metadata_checker_rejects_duplicate_release_paths(tmp_path: Path):
    checker = _checker()
    root = _copy_release_metadata_tree(tmp_path)
    config_path = root / "release-please-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    extra_files = config["packages"]["."]["extra-files"]
    extra_files.append(dict(extra_files[-1]))
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(checker.MetadataError, match="duplicate release-please path"):
        checker.validate_source(root)


def test_release_metadata_checker_requires_a_real_wheel_file(tmp_path: Path):
    checker = _checker()
    archive = tmp_path / "designer.txt"
    with zipfile.ZipFile(archive, "w") as wheel:
        wheel.writestr("placeholder", "not a wheel")

    with pytest.raises(checker.MetadataError, match="wheel"):
        checker._expanded_wheels([str(archive)])


def test_start_server_defers_port_resolution_to_core(monkeypatch):
    from types import SimpleNamespace

    from dcc_mcp_substance3d_designer import server as server_module

    ports = []
    stub = SimpleNamespace(
        is_running=False,
        register_builtin_actions=lambda: None,
        start=lambda: None,
        stop=lambda: None,
    )

    monkeypatch.setattr(server_module, "_server", None)
    monkeypatch.setattr(
        server_module,
        "SubstanceDesignerMcpServer",
        lambda _dispatcher, port=None, enable_gateway_failover=True: (
            ports.append((port, enable_gateway_failover)) or stub
        ),
    )
    monkeypatch.setenv("DCC_MCP_SUBSTANCE3D_DESIGNER_PORT", "8765")

    dispatcher = object()
    server_module.start_server(dispatcher, 0, enable_gateway_failover=False)
    server_module.stop_server()
    server_module.start_server(dispatcher)
    server_module.stop_server()

    assert ports == [(0, False), (None, True)]
