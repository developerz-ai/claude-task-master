"""Validation for user-supplied git branch names.

Mirrors the constraints of `git check-ref-format --branch` closely enough to reject
names git itself would refuse, so a bad `--branch` value fails fast at the CLI rather
than deep inside a work session.
"""

# Characters git forbids anywhere in a ref component, plus whitespace.
_FORBIDDEN = set(" \t\n\r~^:?*[\\")


def is_valid_branch_name(name: str) -> bool:
    """Return True if `name` is a syntactically valid git branch name.

    Rejects the cases git's ref-format check rejects: empty, leading '-', a component
    starting with '.', '..', '@{', trailing '/' or '.lock', a bare '@', consecutive
    slashes, control characters, and the forbidden character set above.
    """
    if not name or name == "@":
        return False
    if name.startswith("-") or name.startswith("/") or name.endswith("/"):
        return False
    if name.endswith(".") or name.endswith(".lock"):
        return False
    if ".." in name or "@{" in name or "//" in name:
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        return False
    if any(ch in _FORBIDDEN for ch in name):
        return False
    # No path component may start with a dot (e.g. `foo/.bar`) or end with `.lock`.
    return all(comp and not comp.startswith(".") for comp in name.split("/"))
