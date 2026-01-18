#!/usr/bin/env python3
"""Version synchronization script for Claude Task Master.

Ensures version consistency across:
    - pyproject.toml (source of truth)
    - src/claude_task_master/__init__.py
    - bin/claudetm (SCRIPT_VERSION)

Usage:
    python scripts/sync_version.py         # Check and sync all versions
    python scripts/sync_version.py --check # Check only, don't modify
    python scripts/sync_version.py --fix   # Fix any mismatches
"""

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple


class VersionInfo(NamedTuple):
    """Version information from a source file."""

    file: str
    version: str | None
    line_number: int | None = None


def get_project_root() -> Path:
    """Find the project root directory."""
    script_dir = Path(__file__).parent.resolve()
    return script_dir.parent


def get_pyproject_version(pyproject_path: Path) -> VersionInfo:
    """Extract version from pyproject.toml (source of truth)."""
    if not pyproject_path.exists():
        return VersionInfo("pyproject.toml", None)

    content = pyproject_path.read_text()
    for i, line in enumerate(content.splitlines(), 1):
        match = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if match:
            return VersionInfo("pyproject.toml", match.group(1), i)

    return VersionInfo("pyproject.toml", None)


def get_init_version(init_path: Path) -> VersionInfo:
    """Extract version from __init__.py."""
    if not init_path.exists():
        return VersionInfo("__init__.py", None)

    content = init_path.read_text()
    for i, line in enumerate(content.splitlines(), 1):
        match = re.match(r'^__version__\s*=\s*["\']([^"\']+)["\']', line)
        if match:
            return VersionInfo("__init__.py", match.group(1), i)

    return VersionInfo("__init__.py", None)


def get_bash_version(bash_path: Path) -> VersionInfo:
    """Extract SCRIPT_VERSION from bash wrapper."""
    if not bash_path.exists():
        return VersionInfo("bin/claudetm", None)

    content = bash_path.read_text()
    for i, line in enumerate(content.splitlines(), 1):
        match = re.match(r'^SCRIPT_VERSION\s*=\s*"([^"]+)"', line)
        if match:
            return VersionInfo("bin/claudetm", match.group(1), i)

    return VersionInfo("bin/claudetm", None)


def update_init_version(init_path: Path, old_version: str, new_version: str) -> bool:
    """Update version in __init__.py."""
    if not init_path.exists():
        print(f"  ERROR: {init_path} not found")
        return False

    content = init_path.read_text()
    new_content = re.sub(
        r'^(__version__\s*=\s*["\'])' + re.escape(old_version) + r'(["\'])',
        rf"\g<1>{new_version}\g<2>",
        content,
        flags=re.MULTILINE,
    )

    if content == new_content:
        print(f"  WARNING: Could not find version {old_version} in {init_path.name}")
        return False

    init_path.write_text(new_content)
    print(f"  Updated {init_path.name}: {old_version} -> {new_version}")
    return True


def update_bash_version(bash_path: Path, old_version: str, new_version: str) -> bool:
    """Update SCRIPT_VERSION in bash wrapper."""
    if not bash_path.exists():
        print(f"  ERROR: {bash_path} not found")
        return False

    content = bash_path.read_text()
    new_content = re.sub(
        r'^(SCRIPT_VERSION\s*=\s*")' + re.escape(old_version) + r'(")',
        rf"\g<1>{new_version}\g<2>",
        content,
        flags=re.MULTILINE,
    )

    if content == new_content:
        print(f"  WARNING: Could not find SCRIPT_VERSION={old_version} in {bash_path.name}")
        return False

    bash_path.write_text(new_content)
    print(f"  Updated {bash_path.name}: {old_version} -> {new_version}")
    return True


def check_versions(verbose: bool = True) -> tuple[str | None, list[VersionInfo], bool]:
    """Check version consistency across all files.

    Returns:
        Tuple of (source_version, all_versions, all_in_sync)
    """
    project_root = get_project_root()

    pyproject_path = project_root / "pyproject.toml"
    init_path = project_root / "src" / "claude_task_master" / "__init__.py"
    bash_path = project_root / "bin" / "claudetm"

    pyproject_info = get_pyproject_version(pyproject_path)
    init_info = get_init_version(init_path)
    bash_info = get_bash_version(bash_path)

    all_versions = [pyproject_info, init_info, bash_info]

    if verbose:
        print("Version check:")
        for info in all_versions:
            status = info.version if info.version else "NOT FOUND"
            line_info = f" (line {info.line_number})" if info.line_number else ""
            print(f"  {info.file}: {status}{line_info}")

    # pyproject.toml is the source of truth
    source_version = pyproject_info.version

    if source_version is None:
        if verbose:
            print("\nERROR: Could not find version in pyproject.toml")
        return None, all_versions, False

    # Check if all versions match
    all_in_sync = all(
        info.version == source_version for info in all_versions if info.version is not None
    )

    # Check for missing versions
    missing = [info for info in all_versions if info.version is None]
    if missing:
        all_in_sync = False

    if verbose:
        print()
        if all_in_sync:
            print(f"All versions are in sync: {source_version}")
        else:
            print(f"Version mismatch detected! Source of truth (pyproject.toml): {source_version}")
            for info in all_versions:
                if info.version is None:
                    print(f"  - {info.file}: MISSING")
                elif info.version != source_version:
                    print(f"  - {info.file}: {info.version} (should be {source_version})")

    return source_version, all_versions, all_in_sync


def sync_versions(dry_run: bool = False) -> bool:
    """Synchronize all versions to match pyproject.toml.

    Returns:
        True if sync was successful (or already in sync)
    """
    source_version, all_versions, all_in_sync = check_versions(verbose=True)

    if source_version is None:
        return False

    if all_in_sync:
        print("\nNo changes needed.")
        return True

    if dry_run:
        print("\nDry run - would update the following files:")
        for info in all_versions:
            if info.file != "pyproject.toml" and info.version != source_version:
                print(f"  - {info.file}: {info.version or 'MISSING'} -> {source_version}")
        return True

    print("\nSynchronizing versions...")
    project_root = get_project_root()

    success = True

    # Update __init__.py if needed
    init_info = next(info for info in all_versions if info.file == "__init__.py")
    if init_info.version != source_version:
        init_path = project_root / "src" / "claude_task_master" / "__init__.py"
        if init_info.version:
            if not update_init_version(init_path, init_info.version, source_version):
                success = False
        else:
            print(f"  ERROR: Cannot update {init_path.name} - version line not found")
            success = False

    # Update bin/claudetm if needed
    bash_info = next(info for info in all_versions if info.file == "bin/claudetm")
    if bash_info.version != source_version:
        bash_path = project_root / "bin" / "claudetm"
        if bash_info.version:
            if not update_bash_version(bash_path, bash_info.version, source_version):
                success = False
        else:
            print(f"  ERROR: Cannot update {bash_path.name} - SCRIPT_VERSION not found")
            success = False

    if success:
        print(f"\nAll versions synchronized to {source_version}")
    else:
        print("\nSome files could not be updated. Please check manually.")

    return success


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Synchronize version across project files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/sync_version.py         # Check and show status
  python scripts/sync_version.py --check # Check only (exit code 1 if mismatch)
  python scripts/sync_version.py --fix   # Fix any mismatches
  python scripts/sync_version.py --dry-run  # Show what would change

The source of truth is pyproject.toml. Other files are updated to match.
        """,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check versions only, exit with code 1 if not in sync",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Fix version mismatches by syncing to pyproject.toml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress output, only return exit code",
    )

    args = parser.parse_args()

    if args.check:
        # Check mode - just verify
        source_version, _, all_in_sync = check_versions(verbose=not args.quiet)
        if source_version is None:
            return 2  # Error finding version
        return 0 if all_in_sync else 1
    elif args.fix or args.dry_run:
        # Fix mode - sync versions
        success = sync_versions(dry_run=args.dry_run)
        return 0 if success else 1
    else:
        # Default: just show status
        source_version, _, all_in_sync = check_versions(verbose=True)
        if source_version is None:
            return 2
        if not all_in_sync:
            print("\nRun with --fix to synchronize versions.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
