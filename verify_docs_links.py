#!/usr/bin/env python3
"""
Verify all documentation links and cross-references are correct.

This script checks:
1. Internal markdown links (e.g., [text](./file.md#anchor))
2. Relative file paths in links
3. Anchor references within files
4. Cross-references between documents
"""

import re
from pathlib import Path

# Colors for output
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def find_markdown_files(root_dir: Path) -> list[Path]:
    """Find all markdown files in the project, excluding .venv and .claude-task-master."""
    md_files = []
    for path in root_dir.rglob("*.md"):
        # Skip .venv, .claude-task-master, and .git directories
        if any(part.startswith(".") for part in path.parts[:-1]):
            continue
        # Skip tmp directory
        if "tmp" in path.parts:
            continue
        md_files.append(path)
    return sorted(md_files)


def extract_links(content: str) -> list[tuple[str, str, int]]:
    """
    Extract markdown links from content.
    Returns list of (link_text, link_url, line_number) tuples.
    """
    links = []
    # Match [text](url) or [text](url#anchor)
    pattern = r"\[([^\]]+)\]\(([^\)]+)\)"

    for i, line in enumerate(content.split("\n"), 1):
        for match in re.finditer(pattern, line):
            text = match.group(1)
            url = match.group(2)
            links.append((text, url, i))

    return links


def extract_anchors(content: str) -> set[str]:
    """
    Extract all heading anchors from markdown content.
    GitHub-style: lowercase, spaces to hyphens, remove special chars.
    """
    anchors = set()

    # Match markdown headings (# Header, ## Header, etc.)
    for line in content.split("\n"):
        match = re.match(r"^#+\s+(.+)$", line)
        if match:
            heading = match.group(1)
            # Convert to anchor format
            # Remove markdown formatting
            heading = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", heading)  # [text](url) -> text
            heading = re.sub(r"`([^`]+)`", r"\1", heading)  # `code` -> code
            # Convert to lowercase and replace spaces with hyphens
            anchor = heading.lower()
            anchor = re.sub(r"[^\w\s-]", "", anchor)  # Remove special chars
            anchor = re.sub(r"\s+", "-", anchor)  # Spaces to hyphens
            anchor = re.sub(r"-+", "-", anchor)  # Multiple hyphens to single
            anchor = anchor.strip("-")  # Remove leading/trailing hyphens
            anchors.add(anchor)

    return anchors


def verify_link(
    link_url: str, source_file: Path, root_dir: Path, file_anchors: dict[Path, set[str]]
) -> tuple[bool, str]:
    """
    Verify a single link is valid.
    Returns (is_valid, error_message).
    """
    # Skip external links (http://, https://, etc.)
    if link_url.startswith(("http://", "https://", "mailto:", "ftp://")):
        return True, ""

    # Skip anchor-only links (verified separately)
    if link_url.startswith("#"):
        anchor_only = link_url[1:]
        if anchor_only in file_anchors.get(source_file, set()):
            return True, ""
        return False, f"Anchor #{anchor_only} not found in {source_file.name}"

    # Parse URL and anchor
    anchor: str | None = None
    if "#" in link_url:
        path_part, anchor = link_url.split("#", 1)
    else:
        path_part = link_url

    # Skip empty paths
    if not path_part:
        return True, ""

    # Resolve relative path from source file
    source_dir = source_file.parent
    target_path = (source_dir / path_part).resolve()

    # Check if file exists
    if not target_path.exists():
        # Try from root directory
        target_path = (root_dir / path_part.lstrip("./")).resolve()
        if not target_path.exists():
            return False, f"File not found: {path_part}"

    # If anchor specified, check it exists
    if anchor:
        if target_path not in file_anchors:
            # File exists but we haven't scanned it (might be outside our scope)
            return True, ""

        if anchor not in file_anchors[target_path]:
            return False, f"Anchor #{anchor} not found in {target_path.relative_to(root_dir)}"

    return True, ""


def main() -> int:
    """Main verification function."""
    root_dir = Path(__file__).parent
    print(f"Scanning documentation in: {root_dir}")
    print()

    # Find all markdown files
    md_files = find_markdown_files(root_dir)
    print(f"Found {len(md_files)} markdown files")
    print()

    # Extract all anchors from all files
    print("Extracting anchors from files...")
    file_anchors: dict[Path, set[str]] = {}
    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        anchors = extract_anchors(content)
        file_anchors[md_file] = anchors
        print(f"  {md_file.relative_to(root_dir)}: {len(anchors)} anchors")
    print()

    # Verify all links
    print("Verifying links...")
    print()

    total_links = 0
    broken_links = 0
    errors_by_file: dict[Path, list[tuple[int, str, str, str]]] = {}

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        links = extract_links(content)

        if not links:
            continue

        file_errors = []
        for link_text, link_url, line_num in links:
            total_links += 1
            is_valid, error_msg = verify_link(link_url, md_file, root_dir, file_anchors)

            if not is_valid:
                broken_links += 1
                file_errors.append((line_num, link_text, link_url, error_msg))

        if file_errors:
            errors_by_file[md_file] = file_errors

    # Print results
    print("=" * 80)
    print("VERIFICATION RESULTS")
    print("=" * 80)
    print()

    if broken_links == 0:
        print(f"{GREEN}✓ All {total_links} links verified successfully!{RESET}")
        return 0
    else:
        print(f"{RED}✗ Found {broken_links} broken links out of {total_links} total links{RESET}")
        print()

        for md_file, errors in sorted(errors_by_file.items()):
            rel_path = md_file.relative_to(root_dir)
            print(f"{YELLOW}{rel_path}{RESET}")
            for line_num, link_text, link_url, error_msg in errors:
                print(f"  Line {line_num}: [{link_text}]({link_url})")
                print(f"    {RED}✗ {error_msg}{RESET}")
            print()

        return 1


if __name__ == "__main__":
    exit(main())
