"""Tests for console output utilities.

This module tests the colored console output functions in console.py:
- ANSI color constants
- _prefix() - orchestrator prefix with timestamp
- _claude_prefix() - Claude prefix with timestamp
- info(), success(), warning(), error() - status messages
- detail() - secondary/dim messages
- tool() - Claude tool usage messages
- stream() - streaming text output
- claude_text() - Claude text responses
- tool_result() - tool result messages
- newline() - newline output
"""

import re
from datetime import datetime

from claude_task_master.core.console import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    MAGENTA,
    ORANGE,
    RED,
    RESET,
    YELLOW,
    _claude_prefix,
    _prefix,
    claude_text,
    detail,
    error,
    info,
    newline,
    stream,
    success,
    tool,
    tool_result,
    warning,
)

# =============================================================================
# ANSI Color Constants Tests
# =============================================================================


class TestColorConstants:
    """Tests for ANSI color code constants."""

    def test_cyan_is_ansi_escape(self):
        """Test CYAN is a valid ANSI escape sequence."""
        assert CYAN.startswith("\033[")
        assert "36" in CYAN  # 36 is cyan

    def test_green_is_ansi_escape(self):
        """Test GREEN is a valid ANSI escape sequence."""
        assert GREEN.startswith("\033[")
        assert "32" in GREEN  # 32 is green

    def test_yellow_is_ansi_escape(self):
        """Test YELLOW is a valid ANSI escape sequence."""
        assert YELLOW.startswith("\033[")
        assert "33" in YELLOW  # 33 is yellow

    def test_red_is_ansi_escape(self):
        """Test RED is a valid ANSI escape sequence."""
        assert RED.startswith("\033[")
        assert "31" in RED  # 31 is red

    def test_magenta_is_ansi_escape(self):
        """Test MAGENTA is a valid ANSI escape sequence."""
        assert MAGENTA.startswith("\033[")
        assert "35" in MAGENTA  # 35 is magenta

    def test_orange_is_256_color(self):
        """Test ORANGE is a 256-color escape sequence."""
        assert ORANGE.startswith("\033[38;5;")
        assert "208" in ORANGE  # 208 is Anthropic orange

    def test_bold_is_ansi_escape(self):
        """Test BOLD is a valid ANSI escape sequence."""
        assert BOLD.startswith("\033[")
        assert "1" in BOLD  # 1 is bold

    def test_dim_is_ansi_escape(self):
        """Test DIM is a valid ANSI escape sequence."""
        assert DIM.startswith("\033[")
        assert "2" in DIM  # 2 is dim

    def test_reset_is_ansi_escape(self):
        """Test RESET is a valid ANSI escape sequence."""
        assert RESET == "\033[0m"

    def test_all_colors_are_strings(self):
        """Test all color constants are strings."""
        colors = [CYAN, GREEN, YELLOW, RED, MAGENTA, ORANGE, BOLD, DIM, RESET]
        for color in colors:
            assert isinstance(color, str)


# =============================================================================
# _prefix() Function Tests
# =============================================================================


class TestPrefixFunction:
    """Tests for _prefix() function."""

    def test_returns_string(self):
        """Test _prefix returns a string."""
        result = _prefix()
        assert isinstance(result, str)

    def test_contains_claudetm(self):
        """Test _prefix contains 'claudetm'."""
        result = _prefix()
        assert "claudetm" in result

    def test_contains_timestamp_format(self):
        """Test _prefix contains HH:MM:SS timestamp."""
        result = _prefix()
        # Match HH:MM:SS pattern
        timestamp_pattern = r"\d{2}:\d{2}:\d{2}"
        assert re.search(timestamp_pattern, result) is not None

    def test_contains_cyan_color(self):
        """Test _prefix contains cyan color code."""
        result = _prefix()
        assert CYAN in result

    def test_contains_bold(self):
        """Test _prefix contains bold code."""
        result = _prefix()
        assert BOLD in result

    def test_contains_reset(self):
        """Test _prefix contains reset code."""
        result = _prefix()
        assert RESET in result

    def test_timestamp_is_current(self):
        """Test _prefix timestamp is approximately current."""
        before = datetime.now().strftime("%H:%M:%S")
        result = _prefix()
        after = datetime.now().strftime("%H:%M:%S")

        # Either before or after time should be in the result
        assert before in result or after in result

    def test_format_structure(self):
        """Test _prefix has correct format structure."""
        result = _prefix()
        # Should be: CYAN + BOLD + [claudetm HH:MM:SS] + RESET
        assert result.startswith(CYAN + BOLD)
        assert result.endswith(RESET)
        assert "[claudetm" in result


# =============================================================================
# _claude_prefix() Function Tests
# =============================================================================


class TestClaudePrefixFunction:
    """Tests for _claude_prefix() function."""

    def test_returns_string(self):
        """Test _claude_prefix returns a string."""
        result = _claude_prefix()
        assert isinstance(result, str)

    def test_contains_claude(self):
        """Test _claude_prefix contains 'claude'."""
        result = _claude_prefix()
        assert "claude" in result

    def test_does_not_contain_claudetm(self):
        """Test _claude_prefix does not contain 'claudetm'."""
        result = _claude_prefix()
        # Remove the expected 'claude' and check there's no 'tm'
        # Actually, check that it's [claude not [claudetm
        assert "[claude " in result
        assert "[claudetm" not in result

    def test_contains_timestamp_format(self):
        """Test _claude_prefix contains HH:MM:SS timestamp."""
        result = _claude_prefix()
        timestamp_pattern = r"\d{2}:\d{2}:\d{2}"
        assert re.search(timestamp_pattern, result) is not None

    def test_contains_orange_color(self):
        """Test _claude_prefix contains orange color code."""
        result = _claude_prefix()
        assert ORANGE in result

    def test_contains_bold(self):
        """Test _claude_prefix contains bold code."""
        result = _claude_prefix()
        assert BOLD in result

    def test_contains_reset(self):
        """Test _claude_prefix contains reset code."""
        result = _claude_prefix()
        assert RESET in result

    def test_format_structure(self):
        """Test _claude_prefix has correct format structure."""
        result = _claude_prefix()
        # Should be: ORANGE + BOLD + [claude HH:MM:SS] + RESET
        assert result.startswith(ORANGE + BOLD)
        assert result.endswith(RESET)
        assert "[claude" in result


# =============================================================================
# info() Function Tests
# =============================================================================


class TestInfoFunction:
    """Tests for info() function."""

    def test_prints_message(self, capsys):
        """Test info prints the message."""
        info("Test message")
        captured = capsys.readouterr()
        assert "Test message" in captured.out

    def test_includes_prefix(self, capsys):
        """Test info includes orchestrator prefix."""
        info("Test message")
        captured = capsys.readouterr()
        assert "claudetm" in captured.out

    def test_default_newline(self, capsys):
        """Test info ends with newline by default."""
        info("Test message")
        captured = capsys.readouterr()
        assert captured.out.endswith("\n")

    def test_custom_end(self, capsys):
        """Test info with custom end parameter."""
        info("Test message", end="")
        captured = capsys.readouterr()
        assert not captured.out.endswith("\n")

    def test_flush_parameter(self, capsys):
        """Test info accepts flush parameter."""
        # This should not raise
        info("Test message", flush=True)
        captured = capsys.readouterr()
        assert "Test message" in captured.out

    def test_empty_message(self, capsys):
        """Test info with empty message."""
        info("")
        captured = capsys.readouterr()
        assert "claudetm" in captured.out

    def test_message_with_special_chars(self, capsys):
        """Test info with special characters."""
        info("Test: 🎯 special <>&")
        captured = capsys.readouterr()
        assert "🎯" in captured.out
        assert "<>&" in captured.out


# =============================================================================
# success() Function Tests
# =============================================================================


class TestSuccessFunction:
    """Tests for success() function."""

    def test_prints_message(self, capsys):
        """Test success prints the message."""
        success("Operation completed")
        captured = capsys.readouterr()
        assert "Operation completed" in captured.out

    def test_includes_green_color(self, capsys):
        """Test success includes green color."""
        success("Test message")
        captured = capsys.readouterr()
        assert GREEN in captured.out

    def test_includes_reset(self, capsys):
        """Test success includes reset code."""
        success("Test message")
        captured = capsys.readouterr()
        assert RESET in captured.out

    def test_includes_prefix(self, capsys):
        """Test success includes orchestrator prefix."""
        success("Test message")
        captured = capsys.readouterr()
        assert "claudetm" in captured.out

    def test_custom_end(self, capsys):
        """Test success with custom end parameter."""
        success("Test message", end="!")
        captured = capsys.readouterr()
        assert captured.out.endswith("!")

    def test_flush_parameter(self, capsys):
        """Test success accepts flush parameter."""
        success("Test message", flush=True)
        captured = capsys.readouterr()
        assert "Test message" in captured.out


# =============================================================================
# warning() Function Tests
# =============================================================================


class TestWarningFunction:
    """Tests for warning() function."""

    def test_prints_message(self, capsys):
        """Test warning prints the message."""
        warning("Warning message")
        captured = capsys.readouterr()
        assert "Warning message" in captured.out

    def test_includes_yellow_color(self, capsys):
        """Test warning includes yellow color."""
        warning("Test message")
        captured = capsys.readouterr()
        assert YELLOW in captured.out

    def test_includes_reset(self, capsys):
        """Test warning includes reset code."""
        warning("Test message")
        captured = capsys.readouterr()
        assert RESET in captured.out

    def test_includes_prefix(self, capsys):
        """Test warning includes orchestrator prefix."""
        warning("Test message")
        captured = capsys.readouterr()
        assert "claudetm" in captured.out

    def test_custom_end(self, capsys):
        """Test warning with custom end parameter."""
        warning("Test message", end="")
        captured = capsys.readouterr()
        assert not captured.out.endswith("\n")

    def test_flush_parameter(self, capsys):
        """Test warning accepts flush parameter."""
        warning("Test message", flush=True)
        captured = capsys.readouterr()
        assert "Test message" in captured.out


# =============================================================================
# error() Function Tests
# =============================================================================


class TestErrorFunction:
    """Tests for error() function."""

    def test_prints_message(self, capsys):
        """Test error prints the message."""
        error("Error occurred")
        captured = capsys.readouterr()
        assert "Error occurred" in captured.out

    def test_includes_red_color(self, capsys):
        """Test error includes red color."""
        error("Test message")
        captured = capsys.readouterr()
        assert RED in captured.out

    def test_includes_reset(self, capsys):
        """Test error includes reset code."""
        error("Test message")
        captured = capsys.readouterr()
        assert RESET in captured.out

    def test_includes_prefix(self, capsys):
        """Test error includes orchestrator prefix."""
        error("Test message")
        captured = capsys.readouterr()
        assert "claudetm" in captured.out

    def test_custom_end(self, capsys):
        """Test error with custom end parameter."""
        error("Test message", end="\n\n")
        captured = capsys.readouterr()
        assert captured.out.endswith("\n\n")

    def test_flush_parameter(self, capsys):
        """Test error accepts flush parameter."""
        error("Test message", flush=True)
        captured = capsys.readouterr()
        assert "Test message" in captured.out


# =============================================================================
# detail() Function Tests
# =============================================================================


class TestDetailFunction:
    """Tests for detail() function."""

    def test_prints_message(self, capsys):
        """Test detail prints the message."""
        detail("Detail message")
        captured = capsys.readouterr()
        assert "Detail message" in captured.out

    def test_includes_dim_color(self, capsys):
        """Test detail includes dim color."""
        detail("Test message")
        captured = capsys.readouterr()
        assert DIM in captured.out

    def test_includes_reset(self, capsys):
        """Test detail includes reset code."""
        detail("Test message")
        captured = capsys.readouterr()
        assert RESET in captured.out

    def test_includes_prefix(self, capsys):
        """Test detail includes orchestrator prefix."""
        detail("Test message")
        captured = capsys.readouterr()
        assert "claudetm" in captured.out

    def test_includes_indentation(self, capsys):
        """Test detail includes indentation."""
        detail("Test message")
        captured = capsys.readouterr()
        # The function adds 3 spaces after prefix
        assert "   Test message" in captured.out

    def test_custom_end(self, capsys):
        """Test detail with custom end parameter."""
        detail("Test message", end="")
        captured = capsys.readouterr()
        assert not captured.out.endswith("\n")

    def test_flush_parameter(self, capsys):
        """Test detail accepts flush parameter."""
        detail("Test message", flush=True)
        captured = capsys.readouterr()
        assert "Test message" in captured.out


# =============================================================================
# tool() Function Tests
# =============================================================================


class TestToolFunction:
    """Tests for tool() function."""

    def test_prints_message(self, capsys):
        """Test tool prints the message."""
        tool("Using Read tool")
        captured = capsys.readouterr()
        assert "Using Read tool" in captured.out

    def test_includes_claude_prefix(self, capsys):
        """Test tool includes claude prefix not claudetm."""
        tool("Test message")
        captured = capsys.readouterr()
        assert "[claude " in captured.out
        assert "[claudetm" not in captured.out

    def test_includes_orange_color(self, capsys):
        """Test tool uses orange color for prefix."""
        tool("Test message")
        captured = capsys.readouterr()
        assert ORANGE in captured.out

    def test_default_newline(self, capsys):
        """Test tool ends with newline by default."""
        tool("Test message")
        captured = capsys.readouterr()
        assert captured.out.endswith("\n")

    def test_custom_end(self, capsys):
        """Test tool with custom end parameter."""
        tool("Test message", end="")
        captured = capsys.readouterr()
        assert not captured.out.endswith("\n")

    def test_flush_parameter(self, capsys):
        """Test tool accepts flush parameter."""
        tool("Test message", flush=True)
        captured = capsys.readouterr()
        assert "Test message" in captured.out


# =============================================================================
# stream() Function Tests
# =============================================================================


class TestStreamFunction:
    """Tests for stream() function."""

    def test_prints_text(self, capsys):
        """Test stream prints the text."""
        stream("Streaming text")
        captured = capsys.readouterr()
        assert "Streaming text" in captured.out

    def test_no_prefix(self, capsys):
        """Test stream does not include any prefix."""
        stream("Test text")
        captured = capsys.readouterr()
        assert "claudetm" not in captured.out
        assert "claude" not in captured.out

    def test_default_no_newline(self, capsys):
        """Test stream does not end with newline by default."""
        stream("Test text")
        captured = capsys.readouterr()
        assert not captured.out.endswith("\n")

    def test_default_flush_true(self, capsys):
        """Test stream has flush=True by default."""
        # Can't directly test flush, but we verify it runs without error
        stream("Test text")
        captured = capsys.readouterr()
        assert captured.out == "Test text"

    def test_custom_end(self, capsys):
        """Test stream with custom end parameter."""
        stream("Test text", end="\n")
        captured = capsys.readouterr()
        assert captured.out == "Test text\n"

    def test_custom_flush(self, capsys):
        """Test stream with flush=False."""
        stream("Test text", flush=False)
        captured = capsys.readouterr()
        assert "Test text" in captured.out

    def test_multiple_streams(self, capsys):
        """Test multiple stream calls concatenate."""
        stream("One")
        stream("Two")
        stream("Three")
        captured = capsys.readouterr()
        assert captured.out == "OneTwoThree"

    def test_empty_string(self, capsys):
        """Test stream with empty string."""
        stream("")
        captured = capsys.readouterr()
        assert captured.out == ""


# =============================================================================
# claude_text() Function Tests
# =============================================================================


class TestClaudeTextFunction:
    """Tests for claude_text() function."""

    def test_prints_message(self, capsys):
        """Test claude_text prints the message."""
        claude_text("Response text")
        captured = capsys.readouterr()
        assert "Response text" in captured.out

    def test_includes_claude_prefix(self, capsys):
        """Test claude_text includes claude prefix."""
        claude_text("Test message")
        captured = capsys.readouterr()
        assert "[claude " in captured.out
        assert "[claudetm" not in captured.out

    def test_includes_orange_color(self, capsys):
        """Test claude_text uses orange color."""
        claude_text("Test message")
        captured = capsys.readouterr()
        assert ORANGE in captured.out

    def test_default_newline(self, capsys):
        """Test claude_text ends with newline by default."""
        claude_text("Test message")
        captured = capsys.readouterr()
        assert captured.out.endswith("\n")

    def test_custom_end(self, capsys):
        """Test claude_text with custom end parameter."""
        claude_text("Test message", end="")
        captured = capsys.readouterr()
        assert not captured.out.endswith("\n")

    def test_flush_parameter(self, capsys):
        """Test claude_text accepts flush parameter."""
        claude_text("Test message", flush=True)
        captured = capsys.readouterr()
        assert "Test message" in captured.out


# =============================================================================
# tool_result() Function Tests
# =============================================================================


class TestToolResultFunction:
    """Tests for tool_result() function."""

    def test_prints_message(self, capsys):
        """Test tool_result prints the message."""
        tool_result("Result: success")
        captured = capsys.readouterr()
        assert "Result: success" in captured.out

    def test_includes_claude_prefix(self, capsys):
        """Test tool_result includes claude prefix."""
        tool_result("Test result")
        captured = capsys.readouterr()
        assert "[claude " in captured.out

    def test_success_uses_green(self, capsys):
        """Test tool_result uses green for success."""
        tool_result("Success message", is_error=False)
        captured = capsys.readouterr()
        assert GREEN in captured.out

    def test_error_uses_red(self, capsys):
        """Test tool_result uses red for errors."""
        tool_result("Error message", is_error=True)
        captured = capsys.readouterr()
        assert RED in captured.out

    def test_default_is_not_error(self, capsys):
        """Test tool_result defaults to success (green)."""
        tool_result("Test result")
        captured = capsys.readouterr()
        assert GREEN in captured.out
        assert RED not in captured.out

    def test_includes_reset(self, capsys):
        """Test tool_result includes reset code."""
        tool_result("Test result")
        captured = capsys.readouterr()
        assert RESET in captured.out

    def test_default_flush_true(self, capsys):
        """Test tool_result has flush=True by default."""
        # Can't directly test flush, but verify it runs
        tool_result("Test result", flush=True)
        captured = capsys.readouterr()
        assert "Test result" in captured.out

    def test_custom_flush(self, capsys):
        """Test tool_result with flush=False."""
        tool_result("Test result", flush=False)
        captured = capsys.readouterr()
        assert "Test result" in captured.out


# =============================================================================
# newline() Function Tests
# =============================================================================


class TestNewlineFunction:
    """Tests for newline() function."""

    def test_prints_newline(self, capsys):
        """Test newline prints a newline."""
        newline()
        captured = capsys.readouterr()
        assert captured.out == "\n"

    def test_multiple_newlines(self, capsys):
        """Test multiple newline calls."""
        newline()
        newline()
        newline()
        captured = capsys.readouterr()
        assert captured.out == "\n\n\n"

    def test_no_other_output(self, capsys):
        """Test newline produces only a newline."""
        newline()
        captured = capsys.readouterr()
        assert len(captured.out) == 1
        assert captured.out[0] == "\n"


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for console output."""

    def test_mixed_output(self, capsys):
        """Test mixed output types."""
        info("Starting task")
        tool("Reading file")
        success("File read successfully")
        warning("File is large")
        error("Error parsing content")
        detail("See log for details")
        newline()

        captured = capsys.readouterr()
        assert "Starting task" in captured.out
        assert "Reading file" in captured.out
        assert "File read successfully" in captured.out
        assert "File is large" in captured.out
        assert "Error parsing content" in captured.out
        assert "See log for details" in captured.out

    def test_streaming_with_messages(self, capsys):
        """Test streaming mixed with messages."""
        info("Beginning stream")
        stream("A")
        stream("B")
        stream("C")
        info("Stream complete")

        captured = capsys.readouterr()
        assert "Beginning stream" in captured.out
        assert "ABC" in captured.out
        assert "Stream complete" in captured.out

    def test_all_functions_produce_output(self, capsys):
        """Test all console functions produce some output."""
        info("info")
        success("success")
        warning("warning")
        error("error")
        detail("detail")
        tool("tool")
        stream("stream")
        claude_text("claude_text")
        tool_result("tool_result")
        newline()

        captured = capsys.readouterr()
        assert len(captured.out) > 0
        # All message types should be present
        assert "info" in captured.out
        assert "success" in captured.out
        assert "warning" in captured.out
        assert "error" in captured.out
        assert "detail" in captured.out
        assert "tool" in captured.out
        assert "stream" in captured.out
        assert "claude_text" in captured.out
        assert "tool_result" in captured.out

    def test_color_codes_present_in_colored_functions(self, capsys):
        """Test color codes are present in appropriate functions."""
        success("msg")
        warning("msg")
        error("msg")
        detail("msg")

        captured = capsys.readouterr()
        assert GREEN in captured.out
        assert YELLOW in captured.out
        assert RED in captured.out
        assert DIM in captured.out

    def test_prefix_differentiation(self, capsys):
        """Test claudetm and claude prefixes are different."""
        info("orchestrator message")
        tool("claude message")

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert "[claudetm" in lines[0]
        assert "[claude " in lines[1]
        assert "[claudetm" not in lines[1]


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests for console output."""

    def test_long_message(self, capsys):
        """Test very long message."""
        long_msg = "A" * 10000
        info(long_msg)
        captured = capsys.readouterr()
        assert long_msg in captured.out

    def test_multiline_message(self, capsys):
        """Test message with newlines."""
        info("Line 1\nLine 2\nLine 3")
        captured = capsys.readouterr()
        assert "Line 1\nLine 2\nLine 3" in captured.out

    def test_unicode_message(self, capsys):
        """Test message with unicode characters."""
        info("Unicode: 日本語 العربية 中文 🎯✓⚠")
        captured = capsys.readouterr()
        assert "日本語" in captured.out
        assert "العربية" in captured.out
        assert "中文" in captured.out
        assert "🎯" in captured.out

    def test_ansi_in_message(self, capsys):
        """Test message containing ANSI codes (edge case)."""
        # Message with embedded ANSI - should pass through
        info(f"Already {RED}colored{RESET} text")
        captured = capsys.readouterr()
        assert "Already" in captured.out
        assert "colored" in captured.out

    def test_none_like_values_in_message(self, capsys):
        """Test message with None-like string."""
        info("None")
        info("null")
        info("undefined")
        captured = capsys.readouterr()
        assert "None" in captured.out
        assert "null" in captured.out
        assert "undefined" in captured.out

    def test_whitespace_only_message(self, capsys):
        """Test message with only whitespace."""
        info("   ")
        captured = capsys.readouterr()
        assert "claudetm" in captured.out

    def test_tab_in_message(self, capsys):
        """Test message with tab characters."""
        info("Col1\tCol2\tCol3")
        captured = capsys.readouterr()
        assert "Col1\tCol2\tCol3" in captured.out

    def test_carriage_return_in_message(self, capsys):
        """Test message with carriage return."""
        info("Before\rAfter")
        captured = capsys.readouterr()
        assert "Before\rAfter" in captured.out


# =============================================================================
# Output Format Verification Tests
# =============================================================================


class TestOutputFormat:
    """Tests to verify exact output format."""

    def test_info_format(self, capsys):
        """Test info output format structure."""
        info("test message")
        captured = capsys.readouterr()
        # Should contain: prefix + space + message + newline
        assert captured.out.count("test message") == 1

    def test_success_format_colors_message(self, capsys):
        """Test success colors the message not the prefix."""
        success("colored")
        captured = capsys.readouterr()
        # Message should be wrapped in green
        assert f"{GREEN}colored{RESET}" in captured.out

    def test_warning_format_colors_message(self, capsys):
        """Test warning colors the message not the prefix."""
        warning("colored")
        captured = capsys.readouterr()
        assert f"{YELLOW}colored{RESET}" in captured.out

    def test_error_format_colors_message(self, capsys):
        """Test error colors the message not the prefix."""
        error("colored")
        captured = capsys.readouterr()
        assert f"{RED}colored{RESET}" in captured.out

    def test_detail_includes_indentation_in_dim(self, capsys):
        """Test detail has indentation within dim section."""
        detail("test")
        captured = capsys.readouterr()
        # Format: prefix + space + DIM + indentation + message + RESET
        assert DIM + "   test" + RESET in captured.out

    def test_tool_result_success_format(self, capsys):
        """Test tool_result success format."""
        tool_result("result", is_error=False)
        captured = capsys.readouterr()
        assert f"{GREEN}result{RESET}" in captured.out

    def test_tool_result_error_format(self, capsys):
        """Test tool_result error format."""
        tool_result("result", is_error=True)
        captured = capsys.readouterr()
        assert f"{RED}result{RESET}" in captured.out
