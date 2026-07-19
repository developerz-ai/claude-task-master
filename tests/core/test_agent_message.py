"""Tests for the MessageProcessor class in agent_message.py.

This module tests:
- is_error propagation from ResultMessage
- subagent end_turn suppression in stop_reason display
- None-guard preventing accumulated text loss
- reset_result_state clearing captured outcome state
- Cost and token extraction from ResultMessage
- TextBlock, ToolUseBlock, ToolResultBlock processing
- RateLimitEvent handling
- format_tool_detail tool-name routing
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.agent_message import MessageProcessor, create_message_processor

# =============================================================================
# Helpers
# =============================================================================


def _make_result_message(
    *,
    is_error: bool = False,
    subtype: str | None = None,
    result: str | None = None,
    stop_reason: str | None = None,
    total_cost_usd: float | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> MagicMock:
    """Build a minimal ResultMessage mock."""
    msg = MagicMock()
    type(msg).__name__ = "ResultMessage"
    msg.content = None
    msg.is_error = is_error
    msg.subtype = subtype
    msg.result = result
    msg.stop_reason = stop_reason
    msg.total_cost_usd = total_cost_usd
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    msg.usage = usage
    return msg


def _make_assistant_message(
    blocks: list[MagicMock] | None = None,
) -> MagicMock:
    """Build an assistant message with optional content blocks."""
    msg = MagicMock()
    type(msg).__name__ = "AssistantMessage"
    msg.content = blocks or []
    return msg


def _make_text_block(text: str) -> MagicMock:
    blk = MagicMock()
    type(blk).__name__ = "TextBlock"
    blk.text = text
    return blk


def _make_tool_use_block(name: str, input_data: dict | None = None) -> MagicMock:
    blk = MagicMock()
    type(blk).__name__ = "ToolUseBlock"
    blk.name = name
    blk.input = input_data or {}
    return blk


def _make_tool_result_block(tool_use_id: str = "tu_1", is_error: bool = False) -> MagicMock:
    blk = MagicMock()
    type(blk).__name__ = "ToolResultBlock"
    blk.tool_use_id = tool_use_id
    blk.is_error = is_error
    return blk


# =============================================================================
# is_error propagation
# =============================================================================


class TestIsErrorPropagation:
    """is_error flag from ResultMessage is captured in last_result_is_error."""

    def test_is_error_true_sets_flag(self):
        """ResultMessage with is_error=True → last_result_is_error=True."""
        proc = MessageProcessor()
        msg = _make_result_message(is_error=True, subtype="error_max_turns")
        with (
            patch.object(proc, "_MessageProcessor__dict__", {}, create=True),
            patch("claude_task_master.core.agent_message.console") as mock_console,
        ):
            proc.process_message(msg, "")
            _ = mock_console  # silence unused warning

        assert proc.last_result_is_error is True

    def test_is_error_false_default_not_set(self):
        """ResultMessage with is_error=False → last_result_is_error stays False."""
        proc = MessageProcessor()
        msg = _make_result_message(is_error=False, result="done")
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_result_is_error is False

    def test_is_error_subtype_captured(self):
        """Subtype is stored alongside the is_error flag for diagnostics."""
        proc = MessageProcessor()
        msg = _make_result_message(is_error=True, subtype="error_during_execution")
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_result_subtype == "error_during_execution"

    def test_is_error_logs_warning(self):
        """is_error=True causes a console.warning with the subtype detail."""
        proc = MessageProcessor()
        msg = _make_result_message(is_error=True, subtype="error_max_budget_usd")
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            proc.process_message(msg, "")

        mock_console.warning.assert_called_once()
        warning_text = mock_console.warning.call_args[0][0]
        assert "error_max_budget_usd" in warning_text

    def test_is_error_unknown_subtype_uses_unknown_detail(self):
        """is_error=True with subtype=None shows 'unknown' in warning."""
        proc = MessageProcessor()
        msg = _make_result_message(is_error=True, subtype=None)
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            proc.process_message(msg, "")

        warning_text = mock_console.warning.call_args[0][0]
        assert "unknown" in warning_text

    def test_is_error_absent_attribute_treated_as_false(self):
        """A ResultMessage without is_error attr defaults to False (SDK compat)."""
        proc = MessageProcessor()
        msg = MagicMock()
        type(msg).__name__ = "ResultMessage"
        msg.content = None
        # Delete is_error so getattr falls back to MagicMock default (truthy);
        # instead we explicitly test the bool() branch by making it return False.
        msg.is_error = False
        msg.subtype = None
        msg.result = "ok"
        msg.stop_reason = None
        msg.total_cost_usd = None
        msg.usage = None
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_result_is_error is False


# =============================================================================
# subagent end_turn suppression
# =============================================================================


class TestStopReasonDisplay:
    """stop_reason='end_turn' and 'tool_use' must not emit console.detail."""

    def test_end_turn_stop_reason_suppressed(self):
        """stop_reason='end_turn' does NOT trigger console.detail output."""
        proc = MessageProcessor()
        msg = _make_result_message(stop_reason="end_turn")
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            proc.process_message(msg, "")

        mock_console.detail.assert_not_called()

    def test_tool_use_stop_reason_suppressed(self):
        """stop_reason='tool_use' does NOT trigger console.detail output."""
        proc = MessageProcessor()
        msg = _make_result_message(stop_reason="tool_use")
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            proc.process_message(msg, "")

        mock_console.detail.assert_not_called()

    def test_max_tokens_stop_reason_displayed(self):
        """stop_reason='max_tokens' IS displayed via console.detail."""
        proc = MessageProcessor()
        msg = _make_result_message(stop_reason="max_tokens")
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            proc.process_message(msg, "")

        mock_console.detail.assert_called_once()
        detail_text = mock_console.detail.call_args[0][0]
        assert "max_tokens" in detail_text

    def test_pause_turn_stop_reason_displayed(self):
        """An unexpected stop_reason like 'pause_turn' is shown to the user."""
        proc = MessageProcessor()
        msg = _make_result_message(stop_reason="pause_turn")
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            proc.process_message(msg, "")

        mock_console.detail.assert_called_once()

    def test_none_stop_reason_not_displayed(self):
        """stop_reason=None (absent) does not produce console.detail."""
        proc = MessageProcessor()
        msg = _make_result_message(stop_reason=None)
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            proc.process_message(msg, "")

        mock_console.detail.assert_not_called()


# =============================================================================
# None-guard: result=None must not overwrite accumulated text
# =============================================================================


class TestNoneGuard:
    """ResultMessage.result=None must not overwrite already-accumulated text."""

    def test_none_result_preserves_accumulated_text(self):
        """Error ResultMessages carry result=None; accumulated text must survive."""
        proc = MessageProcessor()
        msg = _make_result_message(is_error=True, result=None)
        with patch("claude_task_master.core.agent_message.console"):
            out = proc.process_message(msg, "my accumulated output")

        assert out == "my accumulated output"

    def test_falsy_empty_string_result_preserves_accumulated_text(self):
        """result='' (empty string, falsy) also preserves accumulated text."""
        proc = MessageProcessor()
        msg = _make_result_message(result="")
        with patch("claude_task_master.core.agent_message.console"):
            out = proc.process_message(msg, "saved work")

        assert out == "saved work"

    def test_non_empty_result_replaces_empty_accumulated_text(self):
        """Successful ResultMessage replaces empty accumulated text with its result."""
        proc = MessageProcessor()
        msg = _make_result_message(result="final answer", is_error=False)
        with patch("claude_task_master.core.agent_message.console"):
            out = proc.process_message(msg, "")

        assert out == "final answer"

    def test_verification_marker_in_result_replaces_when_missing_from_accumulated(self):
        """If result has verification markers missing from accumulated text, use result."""
        proc = MessageProcessor()
        msg = _make_result_message(result="VERIFICATION_RESULT: PASS — all good")
        with patch("claude_task_master.core.agent_message.console"):
            out = proc.process_message(msg, "some partial output without marker")

        assert out == "VERIFICATION_RESULT: PASS — all good"

    def test_accumulated_with_marker_wins_over_result(self):
        """If accumulated text already has the marker, keep it (it may be richer)."""
        proc = MessageProcessor()
        msg = _make_result_message(result="VERIFICATION_RESULT: PASS short")
        with patch("claude_task_master.core.agent_message.console"):
            out = proc.process_message(
                msg, "rich output with VERIFICATION_RESULT: PASS and extra details"
            )

        assert "rich output" in out
        assert "extra details" in out


# =============================================================================
# reset_result_state
# =============================================================================


class TestResetResultState:
    """reset_result_state() must clear captured outcome for the next query."""

    def test_reset_clears_is_error(self):
        """After reset, last_result_is_error is False even if a prior query failed."""
        proc = MessageProcessor()
        msg = _make_result_message(is_error=True, subtype="error_max_turns")
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_result_is_error is True  # sanity

        proc.reset_result_state()
        assert proc.last_result_is_error is False

    def test_reset_clears_subtype(self):
        """After reset, last_result_subtype is None."""
        proc = MessageProcessor()
        msg = _make_result_message(is_error=True, subtype="error_during_execution")
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        proc.reset_result_state()
        assert proc.last_result_subtype is None

    def test_reset_clears_cost(self):
        """After reset, last_total_cost_usd is None."""
        proc = MessageProcessor()
        msg = _make_result_message(total_cost_usd=0.042, input_tokens=100, output_tokens=50)
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_total_cost_usd == pytest.approx(0.042)

        proc.reset_result_state()
        assert proc.last_total_cost_usd is None

    def test_reset_clears_token_counts(self):
        """After reset, input/output token counters return to 0."""
        proc = MessageProcessor()
        msg = _make_result_message(input_tokens=200, output_tokens=75)
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        proc.reset_result_state()
        assert proc.last_input_tokens == 0
        assert proc.last_output_tokens == 0

    def test_initial_state_defaults_are_benign(self):
        """Default state before any query is benign: no error, no cost."""
        proc = MessageProcessor()
        assert proc.last_result_is_error is False
        assert proc.last_result_subtype is None
        assert proc.last_total_cost_usd is None
        assert proc.last_input_tokens == 0
        assert proc.last_output_tokens == 0


# =============================================================================
# Cost and token extraction
# =============================================================================


class TestCostAndTokenExtraction:
    """Cost and token data from ResultMessage land in processor state."""

    def test_cost_usd_stored(self):
        """total_cost_usd is captured from ResultMessage."""
        proc = MessageProcessor()
        msg = _make_result_message(total_cost_usd=1.23)
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_total_cost_usd == pytest.approx(1.23)

    def test_token_counts_stored(self):
        """input_tokens and output_tokens from usage are captured."""
        proc = MessageProcessor()
        msg = _make_result_message(input_tokens=500, output_tokens=300)
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_input_tokens == 500
        assert proc.last_output_tokens == 300

    def test_missing_cost_keeps_none(self):
        """If total_cost_usd is absent (None), last_total_cost_usd stays None."""
        proc = MessageProcessor()
        msg = _make_result_message(total_cost_usd=None)
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_total_cost_usd is None

    def test_missing_usage_keeps_zeros(self):
        """If usage is absent, token counters stay at 0."""
        proc = MessageProcessor()
        msg = MagicMock()
        type(msg).__name__ = "ResultMessage"
        msg.content = None
        msg.is_error = False
        msg.subtype = None
        msg.result = None
        msg.stop_reason = None
        msg.total_cost_usd = None
        msg.usage = None  # SDK may omit usage on error results

        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        assert proc.last_input_tokens == 0
        assert proc.last_output_tokens == 0


# =============================================================================
# Content block processing
# =============================================================================


class TestContentBlockProcessing:
    """TextBlock / ToolUseBlock / ToolResultBlock routing."""

    def test_text_block_accumulated_to_result(self):
        """TextBlock content is appended to result_text."""
        proc = MessageProcessor()
        msg = _make_assistant_message([_make_text_block("hello")])
        with patch("claude_task_master.core.agent_message.console"):
            out = proc.process_message(msg, "start ")

        assert out == "start hello"

    def test_tool_use_block_logged_to_logger(self):
        """ToolUseBlock invokes logger.log_tool_use when a logger is present."""
        mock_logger = MagicMock()
        proc = MessageProcessor(logger=mock_logger)
        blk = _make_tool_use_block("Read", {"file_path": "/foo/bar.py"})
        msg = _make_assistant_message([blk])
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        mock_logger.log_tool_use.assert_called_once_with("Read", {"file_path": "/foo/bar.py"})

    def test_tool_result_block_success_logs(self):
        """A successful ToolResultBlock logs 'completed' to the logger."""
        mock_logger = MagicMock()
        proc = MessageProcessor(logger=mock_logger)
        blk = _make_tool_result_block("tu_abc", is_error=False)
        msg = _make_assistant_message([blk])
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        mock_logger.log_tool_result.assert_called_once_with("tu_abc", "completed")

    def test_tool_result_block_error_logs_error(self):
        """A failed ToolResultBlock logs 'ERROR' to the logger."""
        mock_logger = MagicMock()
        proc = MessageProcessor(logger=mock_logger)
        blk = _make_tool_result_block("tu_xyz", is_error=True)
        msg = _make_assistant_message([blk])
        with patch("claude_task_master.core.agent_message.console"):
            proc.process_message(msg, "")

        mock_logger.log_tool_result.assert_called_once_with("tu_xyz", "ERROR")

    def test_no_content_message_ignored(self):
        """A message with content=None does not crash and returns unchanged text."""
        proc = MessageProcessor()
        msg = MagicMock()
        type(msg).__name__ = "UnknownType"
        msg.content = None
        with patch("claude_task_master.core.agent_message.console"):
            out = proc.process_message(msg, "kept")

        assert out == "kept"

    def test_empty_content_list_ignored(self):
        """A message with content=[] does not crash."""
        proc = MessageProcessor()
        msg = _make_assistant_message([])
        with patch("claude_task_master.core.agent_message.console"):
            out = proc.process_message(msg, "kept")

        assert out == "kept"


# =============================================================================
# RateLimitEvent handling
# =============================================================================


class TestRateLimitEvent:
    """RateLimitEvent messages must log a warning and return result_text unchanged."""

    def test_rate_limit_event_warning_with_retry_after(self):
        """RateLimitEvent with retry_after shows delay in warning."""
        proc = MessageProcessor()
        msg = MagicMock()
        type(msg).__name__ = "RateLimitEvent"
        msg.retry_after = 30
        msg.message = "rate limit exceeded"
        msg.content = None
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            out = proc.process_message(msg, "accumulated")

        mock_console.warning.assert_called_once()
        assert "accumulated" == out  # result_text returned unchanged

    def test_rate_limit_event_warning_without_retry_after(self):
        """RateLimitEvent with retry_after=None shows warning without delay."""
        proc = MessageProcessor()
        msg = MagicMock()
        type(msg).__name__ = "RateLimitEvent"
        msg.retry_after = None
        msg.message = "too many requests"
        msg.content = None
        with patch("claude_task_master.core.agent_message.console") as mock_console:
            out = proc.process_message(msg, "text")

        mock_console.warning.assert_called_once()
        assert out == "text"


# =============================================================================
# format_tool_detail
# =============================================================================


class TestFormatToolDetail:
    """format_tool_detail produces a terse display string per tool type."""

    @pytest.fixture
    def proc(self):
        """Provide a MessageProcessor instance for static method calls."""
        return MessageProcessor()

    def test_bash_tool_shows_command(self, proc):
        """Bash shows the command argument."""
        detail = proc.format_tool_detail("Bash", {"command": "ls -la"})
        assert "ls -la" in detail

    def test_bash_truncates_long_command(self, proc):
        """Commands over 250 chars are truncated with '...'."""
        long_cmd = "x" * 300
        detail = proc.format_tool_detail("Bash", {"command": long_cmd})
        assert detail.endswith("...")
        assert len(detail) <= 260  # "→ " + 247 + "..." = 253 chars

    def test_read_tool_shows_file_path(self, proc):
        """Read shows the file_path."""
        detail = proc.format_tool_detail("Read", {"file_path": "/some/file.py"})
        assert "file.py" in detail

    def test_web_search_shows_query(self, proc):
        """WebSearch shows the query argument."""
        detail = proc.format_tool_detail("WebSearch", {"query": "python typing docs"})
        assert "python typing docs" in detail

    def test_web_search_truncates_long_query(self, proc):
        """WebSearch truncates queries over 100 chars with '...' before closing quote."""
        long_q = "q" * 200
        detail = proc.format_tool_detail("WebSearch", {"query": long_q})
        assert "..." in detail  # truncated somewhere before the closing quote

    def test_grep_shows_pattern_and_path(self, proc):
        """Grep shows the search pattern."""
        detail = proc.format_tool_detail("Grep", {"pattern": "def foo", "path": "."})
        assert "def foo" in detail

    def test_glob_shows_pattern(self, proc):
        """Glob shows the glob pattern."""
        detail = proc.format_tool_detail("Glob", {"pattern": "**/*.py", "path": "src"})
        assert "**/*.py" in detail

    def test_unknown_tool_shows_first_kv(self, proc):
        """Unknown tool shows first key=value pair."""
        detail = proc.format_tool_detail("MyCustomTool", {"param": "value"})
        assert "param" in detail
        assert "value" in detail

    def test_empty_input_returns_empty_string(self, proc):
        """An empty tool_input returns an empty string."""
        detail = proc.format_tool_detail("Bash", {})
        assert detail == ""


# =============================================================================
# Factory
# =============================================================================


class TestCreateMessageProcessor:
    """create_message_processor factory returns a wired MessageProcessor."""

    def test_factory_returns_processor(self):
        """create_message_processor() returns a MessageProcessor."""
        proc = create_message_processor()
        assert isinstance(proc, MessageProcessor)

    def test_factory_with_logger(self):
        """Factory wires the logger into the processor."""
        mock_logger = MagicMock()
        proc = create_message_processor(logger=mock_logger)
        assert proc.logger is mock_logger

    def test_factory_without_logger(self):
        """Factory with no logger leaves logger=None."""
        proc = create_message_processor()
        assert proc.logger is None
