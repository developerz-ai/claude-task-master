"""Regression guards for the repository documentation link checker.

verify_docs_links.py used to retry a missing relative target against the
repository root. That fallback silently accepted nested documents linking one
directory too high ("../docs/docker.md" inside examples/docker-compose/), so a
broken link looked valid. These tests pin strict resolution against the source
document's own directory.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import verify_docs_links  # noqa: E402

DOCKER_COMPOSE_README = ROOT / "examples" / "docker-compose" / "README.md"
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "ftp://")
RESOURCE_DOCS = ("docker.md", "authentication.md", "webhooks.md", "api-reference.md")


def _relative_links() -> list[tuple[str, str]]:
    """Return the README's non-external, non-anchor-only links."""
    content = DOCKER_COMPOSE_README.read_text(encoding="utf-8")
    return [
        (text, url)
        for text, url, _ in verify_docs_links.extract_links(content)
        if not url.startswith(EXTERNAL_PREFIXES) and not url.startswith("#")
    ]


def test_docker_compose_readme_links_resolve_from_its_own_directory() -> None:
    relative = _relative_links()
    assert relative, "expected the README to contain relative file links"
    for text, url in relative:
        path_part = url.split("#", 1)[0]
        target = (DOCKER_COMPOSE_README.parent / path_part).resolve()
        assert target.exists(), f"{text}: {url} does not resolve from {DOCKER_COMPOSE_README.name}"


def test_docker_compose_readme_resource_links_reach_the_docs_directory() -> None:
    urls = [url for _, url in _relative_links()]
    for name in RESOURCE_DOCS:
        matching = [url for url in urls if url.endswith(name)]
        assert matching, f"{name} is not linked from {DOCKER_COMPOSE_README.name}"
        for url in matching:
            target = (DOCKER_COMPOSE_README.parent / url.split("#", 1)[0]).resolve()
            assert target == (ROOT / "docs" / name).resolve(), f"{url} does not reach {name}"


def test_verify_link_rejects_target_that_only_exists_at_the_repo_root() -> None:
    # Precondition: the file really is present at the repository root, so the
    # removed root fallback would have accepted this link.
    assert (ROOT / "docs" / "docker.md").exists()
    is_valid, message = verify_docs_links.verify_link(
        "../docs/docker.md", DOCKER_COMPOSE_README, ROOT, {}
    )
    assert not is_valid
    assert "File not found" in message


def test_verify_link_accepts_document_relative_target_and_local_anchor() -> None:
    anchors = {
        DOCKER_COMPOSE_README: verify_docs_links.extract_anchors(
            DOCKER_COMPOSE_README.read_text(encoding="utf-8")
        )
    }
    is_valid, message = verify_docs_links.verify_link(
        "../../docs/docker.md", DOCKER_COMPOSE_README, ROOT, anchors
    )
    assert is_valid, message
    is_valid, message = verify_docs_links.verify_link(
        "#additional-resources", DOCKER_COMPOSE_README, ROOT, anchors
    )
    assert is_valid, message
