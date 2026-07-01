"""Strip decorative glyphs from agent-authored PR bodies.

Repos with a no-emoji policy still see stray check/cross glyphs leak into PR bodies,
because the body is written by the agent, not a code template. This removes a curated
set of decorative status marks (and any single space that immediately follows one) while
leaving normal ASCII / markdown untouched. It intentionally targets only these marks, not
all emoji, to avoid mangling legitimate content.
"""

# Variation selector U+FE0F requests emoji presentation; any of the marks below can appear
# either bare (`✓`) or with it (`✓️`), so both forms are stripped.
_VS16 = "️"

# Bare decorative check/cross marks.
_BARE_MARKS = ["✅", "✔", "✓", "❌", "❎", "✗", "✘", "☑", "☒"]


def strip_decorative_glyphs(text: str) -> str:
    """Return `text` with decorative check/cross glyphs removed.

    Each mark is dropped in both its bare (`✓`) and variation-selector (`✓️`) form, along
    with a single following space, so `"✓ done"` becomes `"done"` and a bare `"✓"` becomes
    `""`. Content without these marks is returned unchanged.
    """
    for mark in _BARE_MARKS:
        # VS16 form first so the trailing selector never survives a bare-form strip.
        for glyph in (mark + _VS16, mark):
            text = text.replace(f"{glyph} ", "").replace(glyph, "")
    return text
