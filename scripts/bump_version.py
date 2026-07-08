#!/usr/bin/env python3
"""Version bump script for Sentinel.

Usage:
    python scripts/bump_version.py major    # 0.1.0 -> 1.0.0
    python scripts/bump_version.py minor    # 0.1.0 -> 0.2.0
    python scripts/bump_version.py patch    # 0.1.0 -> 0.1.1
    python scripts/bump_version.py 0.2.0    # Set explicit version
"""

import re
import sys
from pathlib import Path


def get_current_version() -> str:
    """Read version from pyproject.toml."""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    match = re.search(r'version = "(.+?)"', pyproject.read_text())
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a version string into (major, minor, patch)."""
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {version}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def bump(version: str, bump_type: str) -> str:
    """Bump a version string."""
    major, minor, patch = parse_version(version)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        # Try to parse as explicit version
        parse_version(bump_type)  # Validate
        return bump_type


def update_version(new_version: str) -> None:
    """Update version in pyproject.toml and __init__.py."""
    project_root = Path(__file__).parent.parent

    # Update pyproject.toml
    pyproject = project_root / "pyproject.toml"
    content = pyproject.read_text()
    content = re.sub(r'version = ".+?"', f'version = "{new_version}"', content)
    pyproject.write_text(content)

    # Update __init__.py
    init_file = project_root / "src" / "sentinel" / "__init__.py"
    if init_file.exists():
        content = init_file.read_text()
        content = re.sub(r'__version__ = ".+?"', f'__version__ = "{new_version}"', content)
        init_file.write_text(content)

    print(f"Version updated to {new_version}")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    current = get_current_version()
    bump_type = sys.argv[1]

    try:
        new_version = bump(current, bump_type)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Bumping version: {current} -> {new_version}")
    update_version(new_version)


if __name__ == "__main__":
    main()
