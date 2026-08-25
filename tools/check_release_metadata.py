"""Fail closed when release and packaged Skill versions diverge."""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Mapping, Optional

import yaml

PROJECT_NAME_RE = re.compile(r'(?m)^name = "([^"]+)"$')
PROJECT_VERSION_RE = re.compile(r'(?m)^version = "([^"]+)"$')
PACKAGE_VERSION_RE = re.compile(r'(?m)^__version__ = "([^"]+)"')
SKILL_MARKER_RE = re.compile(r'^\s+version:\s*["\']([^"\']+)["\']\s*#\s*x-release-please-version\s*$')
WHEEL_NAME_RE = re.compile(r"(?m)^Name:\s*(\S+)\s*$")
WHEEL_VERSION_RE = re.compile(r"(?m)^Version:\s*(\S+)\s*$")
RELEASE_MARKER = "x-release-please-version"
PACKAGE = "dcc_mcp_substance3d_designer"
DISTRIBUTION = "dcc-mcp-substance3d-designer"
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class MetadataError(RuntimeError):
    """Release metadata is missing, ambiguous, or inconsistent."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise MetadataError("Skill metadata contains an invalid mapping key") from exc
        if duplicate:
            raise MetadataError(f"Skill metadata contains duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _one_match(pattern: re.Pattern[str], text: str, label: str) -> str:
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise MetadataError(f"{label} must contain exactly one version")
    return matches[0]


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MetadataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)


def _canonical_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _yaml_mapping_value(node: yaml.Node, key: str, label: str) -> yaml.Node:
    if not isinstance(node, yaml.MappingNode):
        raise MetadataError(f"{label} must be a mapping")
    matches = [
        value_node
        for key_node, value_node in node.value
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key
    ]
    if len(matches) != 1:
        raise MetadataError(f"{label}.{key} must occur exactly once")
    return matches[0]


def _skill_version(text: str, label: str) -> str:
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise MetadataError(f"{label} Skill metadata must contain one leading YAML frontmatter block")
    try:
        metadata = yaml.load(parts[1], Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise MetadataError(f"{label} Skill metadata is invalid YAML") from exc
    if not isinstance(metadata, Mapping):
        raise MetadataError(f"{label} Skill metadata must be a mapping")
    dcc_metadata = metadata.get("metadata")
    if not isinstance(dcc_metadata, Mapping):
        raise MetadataError(f"{label} Skill metadata.metadata must be a mapping")
    dcc_mcp = dcc_metadata.get("dcc-mcp")
    if not isinstance(dcc_mcp, Mapping):
        raise MetadataError(f"{label} Skill metadata.metadata.dcc-mcp must be a mapping")
    version = dcc_mcp.get("version")
    if not isinstance(version, str) or not version:
        raise MetadataError(f"{label} Skill metadata.metadata.dcc-mcp.version must be a string")
    metadata_node = yaml.compose(parts[1], Loader=_UniqueKeyLoader)
    if metadata_node is None:
        raise MetadataError(f"{label} Skill metadata must be a mapping")
    dcc_metadata_node = _yaml_mapping_value(metadata_node, "metadata", f"{label} Skill metadata")
    dcc_mcp_node = _yaml_mapping_value(
        dcc_metadata_node,
        "dcc-mcp",
        f"{label} Skill metadata.metadata",
    )
    version_node = _yaml_mapping_value(
        dcc_mcp_node,
        "version",
        f"{label} Skill metadata.metadata.dcc-mcp",
    )
    if not isinstance(version_node, yaml.ScalarNode):
        raise MetadataError(f"{label} Skill metadata.metadata.dcc-mcp.version must be a scalar")

    frontmatter_lines = parts[1].splitlines()
    marker_lines = [(index, line) for index, line in enumerate(frontmatter_lines) if RELEASE_MARKER in line]
    if len(marker_lines) != 1:
        raise MetadataError(f"{label} Skill metadata version must have exactly one release-please marker")
    marker_index, marker_line = marker_lines[0]
    marker = SKILL_MARKER_RE.fullmatch(marker_line)
    if marker_index != version_node.start_mark.line or marker is None or marker.group(1) != version:
        raise MetadataError(f"{label} Skill metadata release-please marker must bind the declared version")
    return version


def _source_skill_files(root: Path) -> list[Path]:
    files = sorted((root / "src" / PACKAGE / "skills").glob("*/SKILL.md"))
    if not files:
        raise MetadataError("no packaged Skill metadata found")
    return files


def validate_source(root: Path) -> str:
    project = root / "pyproject.toml"
    package_version = root / "src" / PACKAGE / "__version__.py"
    manifest = root / ".release-please-manifest.json"
    release_config = root / "release-please-config.json"

    project_text = project.read_text(encoding="utf-8")
    project_name = _one_match(PROJECT_NAME_RE, project_text, "pyproject.toml project name")
    if _canonical_distribution(project_name) != DISTRIBUTION:
        raise MetadataError("pyproject.toml distribution identity is unexpected")
    version = _one_match(PROJECT_VERSION_RE, project_text, "pyproject.toml")
    if _one_match(PACKAGE_VERSION_RE, package_version.read_text(encoding="utf-8"), "package version") != version:
        raise MetadataError("package version does not match pyproject.toml")

    manifest_data = _load_json(manifest)
    if not isinstance(manifest_data, dict) or manifest_data.get(".") != version:
        raise MetadataError("release manifest does not match pyproject.toml")

    config_data = _load_json(release_config)
    try:
        extra_files = config_data["packages"]["."]["extra-files"]
    except (KeyError, TypeError) as exc:
        raise MetadataError("release-please extra-files configuration is missing") from exc
    if not isinstance(extra_files, list):
        raise MetadataError("release-please extra-files must be a list")
    configured: list[str] = []
    for entry in extra_files:
        if not isinstance(entry, Mapping) or entry.get("type") != "generic":
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            raise MetadataError("release-please generic path must be a non-empty string")
        if path in configured:
            raise MetadataError(f"duplicate release-please path: {path}")
        configured.append(path)

    skill_files = _source_skill_files(root)
    expected_skill_paths = {path.relative_to(root).as_posix() for path in skill_files}
    configured_skill_paths = {path for path in configured if path.endswith("/SKILL.md")}
    if configured_skill_paths != expected_skill_paths:
        raise MetadataError("release-please Skill path set does not match packaged Skills")

    for skill_file in skill_files:
        relative = skill_file.relative_to(root).as_posix()
        if _skill_version(skill_file.read_text(encoding="utf-8"), relative) != version:
            raise MetadataError(f"{relative} does not match pyproject.toml")
    return version


def _expanded_wheels(patterns: Iterable[str]) -> list[Path]:
    wheels: list[Path] = []
    for pattern in patterns:
        matches = [Path(match) for match in glob.glob(pattern)]
        wheels.extend(matches or [Path(pattern)])
    unique = sorted(
        {
            path.resolve()
            for path in wheels
            if path.suffix == ".whl"
            and path.is_file()
            and not path.is_symlink()
            and not (getattr(path.lstat(), "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
        }
    )
    if len(unique) != 1:
        raise MetadataError("exactly one built wheel is required")
    return unique


def validate_wheel(root: Path, wheel: Path, version: str) -> None:
    if (
        wheel.suffix != ".whl"
        or not wheel.is_file()
        or wheel.is_symlink()
        or getattr(wheel.lstat(), "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise MetadataError("wheel must be one ordinary .whl file")
    project_text = (root / "pyproject.toml").read_text(encoding="utf-8")
    project_name = _one_match(PROJECT_NAME_RE, project_text, "pyproject.toml project name")
    if _canonical_distribution(project_name) != DISTRIBUTION:
        raise MetadataError("source distribution identity is unexpected")
    wheel_distribution = DISTRIBUTION.replace("-", "_")
    expected_filename = f"{wheel_distribution}-{version}-py3-none-any.whl"
    if wheel.name != expected_filename:
        raise MetadataError("wheel filename does not match the expected distribution identity")

    expected_skills = {path.parent.name for path in _source_skill_files(root)}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise MetadataError("wheel contains duplicate archive paths")
        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        expected_metadata = f"{wheel_distribution}-{version}.dist-info/METADATA"
        if metadata_files != [expected_metadata]:
            raise MetadataError("wheel distribution metadata path does not match its filename")
        metadata = archive.read(metadata_files[0]).decode("utf-8")
        metadata_name = _one_match(WHEEL_NAME_RE, metadata, "wheel METADATA Name")
        if _canonical_distribution(metadata_name) != DISTRIBUTION:
            raise MetadataError("wheel METADATA distribution Name does not match source")
        if _one_match(WHEEL_VERSION_RE, metadata, "wheel METADATA") != version:
            raise MetadataError("wheel METADATA version does not match source")

        package_versions = [name for name in names if name == f"{PACKAGE}/__version__.py"]
        if len(package_versions) != 1:
            raise MetadataError("wheel must contain the package version module")
        package_text = archive.read(package_versions[0]).decode("utf-8")
        if _one_match(PACKAGE_VERSION_RE, package_text, "wheel package version") != version:
            raise MetadataError("wheel package version does not match source")

        wheel_skills: dict[str, str] = {}
        prefix = f"{PACKAGE}/skills/"
        for name in names:
            if not name.startswith(prefix) or not name.endswith("/SKILL.md"):
                continue
            relative = name[len(prefix) :]
            parts = relative.split("/")
            if len(parts) != 2 or parts[1] != "SKILL.md" or parts[0] in wheel_skills:
                raise MetadataError("wheel contains ambiguous Skill metadata")
            wheel_skills[parts[0]] = archive.read(name).decode("utf-8")
        if set(wheel_skills) != expected_skills:
            raise MetadataError("wheel Skill metadata set does not match source")
        for skill, text in wheel_skills.items():
            if _skill_version(text, f"wheel Skill {skill}") != version:
                raise MetadataError(f"wheel Skill {skill} does not match source")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", nargs="+", default=[])
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        version = validate_source(root)
        for wheel in _expanded_wheels(args.wheel) if args.wheel else []:
            validate_wheel(root, wheel, version)
    except (MetadataError, OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        print(f"release metadata check failed: {exc}", file=sys.stderr)
        return 1
    print(f"release metadata is consistent for {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
