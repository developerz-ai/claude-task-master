"""Strip decorative glyphs from agent-authored PR bodies.

Repos with a no-emoji policy still see stray check/cross glyphs leak into PR bodies,
because the body is written by the agent, not a code template. This removes a curated
set of decorative status marks (and any single space that immediately follows one) while
leaving normal ASCII / markdown untouched. It intentionally targets only these marks, not
all emoji, to avoid mangling legitimate content.
"""

# Ordered longest-first so variation-selector forms (e.g. "✔️") are removed before "✔".
_DECORATIVE_GLYPHS = [
    "✅",
    "✔️",
    "✔",
    "✓",
    "❌",
    "❎",
    "✗",
    "✘",
    "☑️",
    "☑",
    "☒",
]


def strip_decorative_glyphs(text: str) -> str:
    """Return `text` with decorative check/cross glyphs removed.

    Each glyph is dropped along with a single following space, so `"✓ done"` becomes
    `"done"` and a bare `"✓"` becomes `""`. Content without these glyphs is returned
    unchanged.
    """
    for glyph in _DECORATIVE_GLYPHS:
        text = text.replace(f"{glyph} ", "").replace(glyph, "")
    return text
