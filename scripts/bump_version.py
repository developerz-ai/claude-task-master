#!/usr/bin/env python3
"""Version bump script for Claude Task Master.

Usage:
    python scripts/bump_version.py [major|minor|patch]
    python scripts/bump_version.py --set 1.2.3

This script updates the version in:
    - pyproject.toml
    - src/claude_task_master/__init__.py
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse a semantic version string into (major, minor, patch)."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version_str)
    if not match:
        raise ValueError(f"Invalid version format: {version_str}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_version(current: tuple[int, int, int], bump_type: str) -> tuple[int, int, int]:
    """Bump version according to semver rules."""
    major, minor, patch = current
    if bump_type == "major":
        return (major + 1, 0, 0)
    elif bump_type == "minor":
        return (major, minor + 1, 0)
    elif bump_type == "patch":
        return (major, minor, patch + 1)
    else:
        raise ValueError(f"Invalid bump type: {bump_type}")


def get_current_version(pyproject_path: Path) -> str:
    """Extract current version from pyproject.toml."""
    content = pyproject_path.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def update_pyproject(pyproject_path: Path, old_version: str, new_version: str) -> None:
    """Update version in pyproject.toml."""
    content = pyproject_path.read_text()
    new_content = content.replace(f'version = "{old_version}"', f'version = "{new_version}"')
    pyproject_path.write_text(new_content)
    print(f"Updated pyproject.toml: {old_version} -> {new_version}")


def update_init(init_path: Path, old_version: str, new_version: str) -> None:
    """Update version in __init__.py."""
    content = init_path.read_text()
    new_content = content.replace(
        f'__version__ = "{old_version}"', f'__version__ = "{new_version}"'
    )
    init_path.write_text(new_content)
    print(f"Updated __init__.py: {old_version} -> {new_version}")


def update_changelog(changelog_path: Path, new_version: str) -> None:
    """Update CHANGELOG.md with new version section."""
    if not changelog_path.exists():
        print("CHANGELOG.md not found, skipping")
        return

    content = changelog_path.read_text()
    today = datetime.now().strftime("%Y-%m-%d")

    # Check if this version already exists
    if f"## [{new_version}]" in content:
        print(f"Version {new_version} already in CHANGELOG.md, skipping")
        return

    # Replace [Unreleased] section header with new version
    # Keep the Unreleased section but add new version below it
    unreleased_pattern = r"## \[Unreleased\]\n"
    replacement = f"## [Unreleased]\n\n## [{new_version}] - {today}\n"

    new_content = re.sub(unreleased_pattern, replacement, content, count=1)

    # Also update the comparison links at the bottom
    # Find the Unreleased link and update it, add new version link
    link_pattern = r"\[Unreleased\]: (https://github\.com/[^/]+/[^/]+)/compare/v([^.]+\.[^.]+\.[^.]+)\.\.\.HEAD"
    link_match = re.search(link_pattern, new_content)

    if link_match:
        repo_url = link_match.group(1)
        old_version_in_link = link_match.group(2)
        # Update unreleased link to compare from new version
        new_unreleased_link = f"[Unreleased]: {repo_url}/compare/v{new_version}...HEAD"
        new_version_link = (
            f"[{new_version}]: {repo_url}/compare/v{old_version_in_link}...v{new_version}"
        )

        # Replace old unreleased link
        new_content = re.sub(
            link_pattern,
            new_unreleased_link + "\n" + new_version_link,
            new_content,
        )

    changelog_path.write_text(new_content)
    print(f"Updated CHANGELOG.md for version {new_version}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Bump project version")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "bump_type",
        nargs="?",
        choices=["major", "minor", "patch"],
        help="Type of version bump",
    )
    group.add_argument(
        "--set",
        dest="set_version",
        metavar="VERSION",
        help="Set a specific version (e.g., 1.2.3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    pyproject_path = project_root / "pyproject.toml"
    init_path = project_root / "src" / "claude_task_master" / "__init__.py"
    changelog_path = project_root / "CHANGELOG.md"

    if not pyproject_path.exists():
        print(f"Error: {pyproject_path} not found")
        return 1

    # Get current version
    current_version = get_current_version(pyproject_path)
    print(f"Current version: {current_version}")

    # Calculate new version
    if args.set_version:
        # Validate the provided version
        try:
            parse_version(args.set_version)
        except ValueError as e:
            print(f"Error: {e}")
            return 1
        new_version = args.set_version
    else:
        current_tuple = parse_version(current_version)
        new_tuple = bump_version(current_tuple, args.bump_type)
        new_version = f"{new_tuple[0]}.{new_tuple[1]}.{new_tuple[2]}"

    print(f"New version: {new_version}")

    if args.dry_run:
        print("\nDry run - no changes made")
        return 0

    # Update files
    update_pyproject(pyproject_path, current_version, new_version)
    update_init(init_path, current_version, new_version)
    update_changelog(changelog_path, new_version)

    print(f"\nVersion bumped to {new_version}")
    print("\nNext steps:")
    print("  1. Review changes: git diff")
    print(f"  2. Commit: git commit -am 'chore: bump version to {new_version}'")
    print(f"  3. Tag: git tag v{new_version}")
    print("  4. Push: git push && git push --tags")

    return 0


if __name__ == "__main__":
    sys.exit(main())
