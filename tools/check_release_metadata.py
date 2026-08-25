"""Fail closed when release and packaged Skill versions diverge."""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Optional

PROJECT_VERSION_RE = re.compile(r'(?m)^version = "([^"]+)"$')
PACKAGE_VERSION_RE = re.compile(r'(?m)^__version__ = "([^"]+)"')
SKILL_VERSION_RE = re.compile(r'(?m)^\s+version:\s*["\']([^"\']+)["\']\s*(?:#.*)?$')
WHEEL_VERSION_RE = re.compile(r"(?m)^Version:\s*(\S+)\s*$")
RELEASE_MARKER = "x-release-please-version"
PACKAGE = "dcc_mcp_substance3d_designer"


class MetadataError(RuntimeError):
    """Release metadata is missing, ambiguous, or inconsistent."""


def _one_match(pattern: re.Pattern[str], text: str, label: str) -> str:
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise MetadataError(f"{label} must contain exactly one version")
    return matches[0]


def _skill_version(text: str, label: str) -> str:
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise MetadataError(f"{label} must contain one leading YAML frontmatter block")
    version = _one_match(SKILL_VERSION_RE, parts[1], label)
    version_line = next(line for line in parts[1].splitlines() if SKILL_VERSION_RE.fullmatch(line))
    if RELEASE_MARKER not in version_line:
        raise MetadataError(f"{label} version is not managed by release-please")
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

    version = _one_match(PROJECT_VERSION_RE, project.read_text(encoding="utf-8"), "pyproject.toml")
    if _one_match(PACKAGE_VERSION_RE, package_version.read_text(encoding="utf-8"), "package version") != version:
        raise MetadataError("package version does not match pyproject.toml")

    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest_data, dict) or manifest_data.get(".") != version:
        raise MetadataError("release manifest does not match pyproject.toml")

    config_data = json.loads(release_config.read_text(encoding="utf-8"))
    try:
        extra_files = config_data["packages"]["."]["extra-files"]
    except (KeyError, TypeError) as exc:
        raise MetadataError("release-please extra-files configuration is missing") from exc
    if not isinstance(extra_files, list):
        raise MetadataError("release-please extra-files must be a list")
    configured = {
        entry.get("path")
        for entry in extra_files
        if isinstance(entry, dict) and entry.get("type") == "generic" and isinstance(entry.get("path"), str)
    }

    for skill_file in _source_skill_files(root):
        relative = skill_file.relative_to(root).as_posix()
        if relative not in configured:
            raise MetadataError(f"{relative} is not tracked by release-please")
        if _skill_version(skill_file.read_text(encoding="utf-8"), relative) != version:
            raise MetadataError(f"{relative} does not match pyproject.toml")
    return version


def _expanded_wheels(patterns: Iterable[str]) -> list[Path]:
    wheels: list[Path] = []
    for pattern in patterns:
        matches = [Path(match) for match in glob.glob(pattern)]
        wheels.extend(matches or [Path(pattern)])
    unique = sorted({path.resolve() for path in wheels if path.is_file()})
    if len(unique) != 1:
        raise MetadataError("exactly one built wheel is required")
    return unique


def validate_wheel(root: Path, wheel: Path, version: str) -> None:
    expected_skills = {path.parent.name for path in _source_skill_files(root)}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise MetadataError("wheel must contain exactly one METADATA file")
        metadata = archive.read(metadata_files[0]).decode("utf-8")
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
    except (MetadataError, OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"release metadata check failed: {exc}", file=sys.stderr)
        return 1
    print(f"release metadata is consistent for {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
