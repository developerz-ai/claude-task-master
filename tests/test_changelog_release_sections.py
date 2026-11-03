"""Guard: every release in CHANGELOG.md is headed once, linked once and has notes.

The changelog once carried two `## [0.1.91]` headings, the second one empty.
That duplicate cost 0.1.91 nothing that had been published: the body a tag
publishes is cut by `.github/workflows/publish.yml:147-154` from the FIRST
`## [X.Y.Z]` heading matching the version up to the next `## [` heading, and
the populated section came first. It blocked no later release either:
`scripts/bump_version.py:78-80` refuses to add a heading only when the
version being bumped to already has one, so a duplicate of another version
does not stand in the way of the next release's entry.

What the duplicate left behind was a hazard in the extraction and an empty
section in the file. The extraction depends on the order of two headings for
one version - had the empty one come first, the release would have published
a generic message instead of its notes - and an empty section publishes
nothing a reader can use. These guards read the committed file only, never a
published artifact, and fail when a release label heads two sections, when a
release section carries no note, or when the bottom compare-link block does
not link a heading exactly once.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CHANGELOG = _ROOT / "CHANGELOG.md"


def _lines() -> list[str]:
    """The committed changelog, split into lines."""
    return _CHANGELOG.read_text(encoding="utf-8").splitlines()


def _is_link_definition(line: str) -> bool:
    """Whether a line is a reference link of the form ``[label]: url``."""
    return line.startswith("[") and "]: " in line


def _link_block(lines: list[str]) -> list[str]:
    """The trailing block of reference links (link lines and blank lines)."""
    start = len(lines)
    while start > 0 and (not lines[start - 1].strip() or _is_link_definition(lines[start - 1])):
        start -= 1
    return lines[start:]


def _release_labels(lines: list[str]) -> list[str]:
    """Labels of the level-2 release headings, in file order."""
    labels: list[str] = []
    for line in lines:
        if not line.startswith("## ["):
            continue
        closing = line.find("]")
        if closing != -1:
            labels.append(line[4:closing])
    return labels


def _link_definitions(lines: list[str]) -> list[tuple[str, str]]:
    """(label, url) pairs of the reference links in the bottom link block."""
    definitions: list[tuple[str, str]] = []
    for line in _link_block(lines):
        if not _is_link_definition(line):
            continue
        label = line[1 : line.index("]")]
        url = line[line.index("]: ") + 3 :].strip()
        definitions.append((label, url))
    return definitions


def _is_version(label: str) -> bool:
    """Whether a release label is a plain semantic version."""
    parts = label.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def _release_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """(label, body) pairs for the release headings, in file order.

    A body is the lines between one `## [X.Y.Z]` heading and the next `## [`
    heading - exactly what publish.yml extracts for that heading
    (`.github/workflows/publish.yml:147-154`).
    """
    headings = [index for index, line in enumerate(lines) if line.startswith("## [")]
    sections: list[tuple[str, list[str]]] = []
    for position, index in enumerate(headings):
        end = headings[position + 1] if position + 1 < len(headings) else len(lines)
        heading = lines[index]
        closing = heading.find("]")
        label = heading[4:closing] if closing != -1 else ""
        sections.append((label, lines[index + 1 : end]))
    return sections


def _has_note(body: list[str]) -> bool:
    """Whether a release body carries at least one note.

    Blank lines, `###` sub-headings and the reference links of the bottom
    block say nothing about the release; a note is any other content line.
    """
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or _is_link_definition(stripped):
            continue
        return True
    return False


def test_release_headings_are_unique() -> None:
    """A release label must head exactly one section."""
    counts = Counter(_release_labels(_lines()))
    duplicates = sorted(label for label, count in counts.items() if count > 1)
    assert not duplicates, f"release heading repeated: {duplicates}"


def test_every_release_heading_has_exactly_one_compare_link() -> None:
    """Each release heading must be linked once from the bottom link block."""
    lines = _lines()
    headings = _release_labels(lines)
    links = Counter(label for label, _ in _link_definitions(lines))

    unlinked = sorted(label for label in headings if links[label] == 0)
    assert not unlinked, f"release heading without a compare link: {unlinked}"

    repeated = sorted(label for label, count in links.items() if count > 1)
    assert not repeated, f"compare link defined more than once: {repeated}"


def test_compare_links_point_at_the_release_they_label() -> None:
    """A compare link must end at the version whose heading it labels."""
    for label, url in _link_definitions(_lines()):
        assert url.startswith("https://"), f"{label}: {url} is not an absolute URL"
        if _is_version(label):
            assert url.endswith(f"v{label}"), f"{label}: {url} does not compare into {label}"
        else:
            assert url.endswith("HEAD"), f"{label}: {url} does not compare into HEAD"


def test_each_release_publishes_one_non_empty_body() -> None:
    """Every release must publish one body, and that body must carry a note.

    publish.yml takes the FIRST `## [X.Y.Z]` heading matching the version and
    publishes the section up to the next `## [` heading, falling back to a
    generic "Release version X" line when that section is empty. A second
    heading for the same version therefore ends the published body at that
    heading, so whichever section comes second never reaches the release, and
    a section holding no note publishes nothing a reader can use.
    """
    sections: dict[str, list[list[str]]] = {}
    for label, body in _release_sections(_lines()):
        if not _is_version(label):
            continue
        sections.setdefault(label, []).append(body)

    problems: list[str] = []
    for label, bodies in sorted(sections.items()):
        if len(bodies) > 1:
            problems.append(f"{label}: {len(bodies)} sections")
        if not all(_has_note(body) for body in bodies):
            problems.append(f"{label}: section without a note")
    assert not problems, f"release body not publishable: {problems}"
