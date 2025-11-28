#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# ///
"""Bump the version in src/lancompute/__init__.py."""

import re
import sys
from pathlib import Path

INIT_FILE = Path(__file__).parent.parent / "src" / "lancompute" / "__init__.py"
VERSION_PATTERN = re.compile(r'__version__\s*=\s*["\'](\d+)\.(\d+)\.(\d+)["\']')


def get_version() -> str:
    """Get the current version."""
    content = INIT_FILE.read_text()
    match = VERSION_PATTERN.search(content)
    if not match:
        raise ValueError("Could not find __version__ in __init__.py")
    return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"


def bump(part: str) -> str:
    """Bump the version by the specified part."""
    content = INIT_FILE.read_text()
    match = VERSION_PATTERN.search(content)
    if not match:
        raise ValueError("Could not find __version__ in __init__.py")

    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))

    if part == "major":
        major += 1
        minor = patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid part: {part}. Use major, minor, or patch.")

    new_version = f"{major}.{minor}.{patch}"
    new_content = VERSION_PATTERN.sub(f'__version__ = "{new_version}"', content)
    INIT_FILE.write_text(new_content)
    return new_version


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(f"Current version: {get_version()}")
        sys.exit(0)

    if len(sys.argv) != 2 or sys.argv[1] not in ("major", "minor", "patch"):
        print("Usage: uv run scripts/bump_version.py [major|minor|patch]")
        print("       uv run scripts/bump_version.py  # show current version")
        sys.exit(1)

    new_ver = bump(sys.argv[1])
    print(f"Bumped version to {new_ver}")
