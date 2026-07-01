"""Unit tests for PR body decorative-glyph sanitization."""

from claude_task_master.github.pr_body_sanitizer import strip_decorative_glyphs


def test_strips_inline_check_and_following_space() -> None:
    assert strip_decorative_glyphs("✓ done") == "done"


def test_strips_bare_glyph() -> None:
    assert strip_decorative_glyphs("status: ✓") == "status: "


def test_strips_variation_selector_form() -> None:
    assert strip_decorative_glyphs("✔️ ok") == "ok"


def test_strips_multiple_mark_types() -> None:
    body = "## Verification\n- ✓ tests pass\n- ❌ lint fails\n- ✅ built"
    cleaned = strip_decorative_glyphs(body)
    for glyph in ("✓", "❌", "✅", "✔"):
        assert glyph not in cleaned
    assert "tests pass" in cleaned
    assert "lint fails" in cleaned


def test_leaves_plain_content_untouched() -> None:
    body = "## Summary\nAdds a feature.\n\n## Changes\n- edited foo.py"
    assert strip_decorative_glyphs(body) == body


def test_does_not_touch_ascii_check_words() -> None:
    # The literal word "check" and ASCII markers must survive.
    assert strip_decorative_glyphs("check the [x] box") == "check the [x] box"
