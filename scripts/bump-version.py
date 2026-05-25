from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?$")
STABLE_VERSION_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
PROJECT_VERSION_RE = re.compile(r'(?m)^version = "([^"]+)"$')
BUMP_PARTS = ("major", "minor", "patch")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bump project version.")
    parser.add_argument("version", nargs="?", help="Version to prepare, for example: 0.1.4")
    parser.add_argument(
        "--bump",
        choices=BUMP_PARTS,
        help="Derive the next version by bumping the current project version.",
    )
    return parser.parse_args()


def _project_version(pyproject: Path) -> str:
    match = PROJECT_VERSION_RE.search(pyproject.read_text())
    if match is None:
        raise SystemExit("Could not find project version in pyproject.toml")
    return match.group(1)


def _bump_version(version: str, part: str) -> str:
    match = STABLE_VERSION_RE.fullmatch(version)
    if match is None:
        raise SystemExit(f"Cannot {part}-bump non-stable version: {version}")

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))

    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1

    return f"{major}.{minor}.{patch}"


def _replace_project_version(pyproject: Path, version: str) -> str:
    text = pyproject.read_text()
    match = PROJECT_VERSION_RE.search(text)
    if match is None:
        raise SystemExit("Could not find project version in pyproject.toml")

    previous_version = match.group(1)
    pyproject.write_text(PROJECT_VERSION_RE.sub(f'version = "{version}"', text, count=1))
    return previous_version

def main() -> None:
    args = _parse_args()
    pyproject = Path("pyproject.toml")

    if bool(args.version) == bool(args.bump):
        raise SystemExit("Specify exactly one of VERSION or --bump")

    version = (
        _bump_version(_project_version(pyproject), args.bump) if args.bump else args.version.strip()
    )
    if VERSION_RE.fullmatch(version) is None:
        raise SystemExit(f"Invalid version: {version}")

    previous_version = _replace_project_version(pyproject, version)
    if previous_version == version:
        raise SystemExit(f"pyproject.toml is already at version {version}")

    print(f"Bumped hf-agentfinder from {previous_version} to {version}")


if __name__ == "__main__":
    main()
