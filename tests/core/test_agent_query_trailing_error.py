"""Tests for stream errors that arrive after the SDK's terminal ResultMessage.

Regression: an unattended run died on a transient API blip. The CLI reported
``API Error: Connection closed mid-response``, emitted a ResultMessage with
``is_error=True`` (subtype "success"), then exited non-zero on purpose — which
the SDK surfaces as ``Exception("Claude Code returned an error result: ...")``
from the *next* ``__anext__()``. That trailing exception was classified as a
generic QueryExecutionError and re-raised, so the orchestrator turned a
one-task hiccup into ``WorkSessionError`` → run blocked, instead of taking the
"ran_incomplete" path the terminal result was already describing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.agent import AgentWrapper, ModelType
from claude_task_master.core.agent_exceptions import ConsecutiveFailuresError
from claude_task_master.core.rate_limit import RateLimitConfig


def _result_message(*, is_error: bool = False, subtype: str = "success", result=None):
    """Build a fake SDK ResultMessage (identified by class name, as in prod)."""
    msg = MagicMock()
    type(msg).__name__ = "ResultMessage"
    msg.is_error = is_error
    msg.subtype = subtype
    msg.result = result
    msg.stop_reason = "stop_sequence"
    msg.total_cost_usd = None
    msg.usage = None
    msg.content = None
    return msg


def _text_message(text: str):
    """Build a fake AssistantMessage carrying a single TextBlock."""
    block = MagicMock()
    type(block).__name__ = "TextBlock"
    block.text = text
    msg = MagicMock()
    type(msg).__name__ = "AssistantMessage"
    msg.content = [block]
    msg.parent_tool_use_id = None
    msg.stop_reason = "stop_sequence"
    return msg


@pytest.fixture
def agent(temp_dir):
    """Create an AgentWrapper instance for testing."""
    mock_sdk = MagicMock()
    mock_sdk.query = AsyncMock()
    mock_sdk.ClaudeAgentOptions = MagicMock()

    with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
        return AgentWrapper(
            access_token="test-token",
            model=ModelType.SONNET,
            working_dir=str(temp_dir),
        )


class TestTrailingErrorAfterTerminalResult:
    """A post-terminal-result stream error must not fail the query."""

    @pytest.mark.asyncio
    async def test_trailing_error_after_result_message_is_not_raised(self, agent):
        """Regression: the CLI's deliberate non-zero exit after an error result
        arrives as a bare Exception on the next __anext__(). Raising it killed
        the run; the session is already over, so return the accumulated text."""
        attempts = 0

        async def error_result_then_process_exit(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            yield _text_message("partial work")
            yield _result_message(is_error=True, subtype="success")
            raise Exception("Claude Code returned an error result: success")

        agent._query_executor.query = error_result_then_process_exit

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await agent._run_query("test prompt", ["Read"])

        # No exception, no retry — the terminal result already said its piece.
        assert attempts == 1
        assert "partial work" in result

    def test_work_session_reports_incomplete_instead_of_blocking(self, agent):
        """Regression: the whole point of not raising is that the caller gets
        success=False and reruns the task ("ran_incomplete"), rather than the
        orchestrator wrapping an AgentError in WorkSessionError and blocking."""

        async def error_result_then_process_exit(*args, **kwargs):
            yield _text_message("started the task")
            yield _result_message(is_error=True, subtype="success")
            raise Exception("Claude Code returned an error result: success")

        agent._query_executor.query = error_result_then_process_exit

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = agent.run_work_session(task_description="do the thing")

        assert result["success"] is False
        assert result["subtype"] == "success"
        assert "started the task" in result["output"]

    @pytest.mark.asyncio
    async def test_trailing_stall_after_result_message_is_not_fatal(self, agent):
        """A stream that never closes after the terminal result must end the
        session on the short post-completion timeout, not raise StreamStallError
        and not park for the full 30-minute idle ceiling."""
        import asyncio as _asyncio

        async def result_then_hang(*args, **kwargs):
            yield _result_message(result="all done")
            await _asyncio.Future()
            yield  # unreachable

        agent._query_executor.query = result_then_hang

        with (
            patch("claude_task_master.core.agent_query.POST_COMPLETION_IDLE_TIMEOUT_SEC", 0.001),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await agent._run_query("test prompt", ["Read"])

        assert result == "all done"

    @pytest.mark.asyncio
    async def test_error_before_any_result_message_still_raises(self, agent):
        """The guard is scoped to post-terminal teardown: an unclassified error
        with no terminal result to fall back on must still reach the retry
        path, so a real failure is never silently reported as an empty run."""
        attempts = 0

        async def always_fails(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            yield _text_message("thinking")
            raise Exception("Claude Code process exited with code 1")

        agent._query_executor.query = always_fails

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConsecutiveFailuresError):
                await agent._run_query("test prompt", ["Read"])

        assert attempts > 1


class TestUnclassifiedErrorRetry:
    """An unclassified API/CLI failure is retried, not fatal on first sight."""

    @pytest.fixture
    def agent(self, temp_dir):
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            return AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
                rate_limit_config=RateLimitConfig(max_retries=3, initial_backoff=0.01),
            )

    @pytest.mark.asyncio
    async def test_unclassified_error_retries_then_succeeds(self, agent):
        """Regression: a generic QueryExecutionError (no keyword the classifier
        recognises) ended an unattended run on its first occurrence. It is
        transient far more often than not — retry it under the failure budget."""
        attempts = 0

        async def fails_once(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise Exception("Claude Code process exited with code 1")
                yield  # unreachable
            yield _result_message(result="recovered")

        agent._query_executor.query = fails_once

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await agent._run_query("test prompt", ["Read"])

        assert attempts == 2
        assert result == "recovered"
