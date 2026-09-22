#!/usr/bin/env python3
"""
Version bumping script for the backend.
Updates version in pyproject.toml and optionally creates a git tag.
"""

import argparse
import re
import sys
from pathlib import Path


def get_current_version(pyproject_path: Path) -> str:
    """Extract current version from pyproject.toml."""
    content = pyproject_path.read_text()
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    if not match:
        print("Error: Could not find version in pyproject.toml")
        sys.exit(1)
    return match.group(1)


def bump_version(version: str, bump_type: str) -> str:
    """Bump version according to semver rules."""
    parts = version.split(".")
    if len(parts) != 3:
        print(
            f"Error: Invalid version format '{version}'. Expected 'major.minor.patch'"
        )
        sys.exit(1)

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        print(
            f"Error: Invalid bump type '{bump_type}'. Use 'major', 'minor', or 'patch'"
        )
        sys.exit(1)

    return f"{major}.{minor}.{patch}"


def update_version_in_file(pyproject_path: Path, new_version: str) -> None:
    """Update version in pyproject.toml file."""
    content = pyproject_path.read_text()
    new_content = re.sub(
        r'version\s*=\s*"[^"]+"', f'version = "{new_version}"', content
    )
    pyproject_path.write_text(new_content)


def main():
    parser = argparse.ArgumentParser(description="Bump version in pyproject.toml")
    parser.add_argument(
        "bump_type", choices=["major", "minor", "patch"], help="Type of version bump"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--tag", action="store_true", help="Create git tag after bumping version"
    )

    args = parser.parse_args()

    # Find pyproject.toml
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        print("Error: pyproject.toml not found in current directory")
        sys.exit(1)

    current_version = get_current_version(pyproject_path)
    new_version = bump_version(current_version, args.bump_type)

    print(f"Current version: {current_version}")
    print(f"New version: {new_version}")

    if args.dry_run:
        print("Dry run - no changes made")
        return

    # Update version
    update_version_in_file(pyproject_path, new_version)
    print(f"Updated pyproject.toml to version {new_version}")

    # Create git tag if requested
    if args.tag:
        import subprocess

        try:
            subprocess.run(["git", "add", "pyproject.toml"], check=True)
            subprocess.run(
                ["git", "commit", "-m", f"chore: bump version to {new_version}"],
                check=True,
            )
            subprocess.run(
                ["git", "tag", "-a", f"v{new_version}", "-m", f"Version {new_version}"],
                check=True,
            )
            print(f"Created git tag v{new_version}")
        except subprocess.CalledProcessError as e:
            print(f"Error creating git tag: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
