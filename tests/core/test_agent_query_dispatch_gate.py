"""Tests for the dispatch gate on queries that may not fan out.

Regression: withholding the ``hive-worker`` definition was believed to be what
made fan-out impossible. It is not — the CLI registers built-in dispatch types
(``general-purpose``, ``Explore``, ``Plan``) on every query regardless of
``agents=``, verified live against a real session. So every phase documented as
"never fans out" — planning, verification, release checks, learnings extraction
and every push-only fix session — could still spawn subagents, just unguarded
ones: no ``background=False``, no ``disallowedTools``, no worker contract. A
review-fix session was observed dispatching two ``general-purpose`` agents that
edited the same tree concurrently and collided on a shared file.

The capability is now denied, not merely unadvertised.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from claude_task_master.core.agent_models import ModelType
from claude_task_master.core.agent_query import AgentQueryExecutor
from claude_task_master.core.agent_query_execute import DISPATCH_TOOLS
from claude_task_master.core.circuit_breaker import CircuitBreaker
from claude_task_master.core.rate_limit import RateLimitConfig


async def _capture_options(tmp_path, get_agents_func: Any) -> dict[str, Any]:
    """Run one query attempt and return the kwargs handed to the SDK options."""
    captured: dict[str, Any] = {}

    def options_class(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return MagicMock()

    async def query(*_args: Any, **_kwargs: Any):
        yield MagicMock(content=None)

    executor = AgentQueryExecutor(
        query_func=query,
        options_class=options_class,
        working_dir=str(tmp_path),
        model=ModelType.SONNET,
        rate_limit_config=RateLimitConfig(),
        circuit_breaker=CircuitBreaker("test"),
    )
    await executor._execute_query(
        "prompt",
        [],
        get_model_name_func=lambda _m: "claude-sonnet-5",
        get_agents_func=get_agents_func,
    )
    return captured


class TestDispatchIsDeniedWhereFanOutIsNot:
    @pytest.mark.asyncio
    async def test_no_agent_loader_denies_the_dispatch_tools(self, tmp_path):
        """A push-only fix session got no worker definitions — and could still fan out."""
        captured = await _capture_options(tmp_path, None)

        assert captured["disallowed_tools"] == list(DISPATCH_TOOLS)
        assert "Task" in captured["disallowed_tools"]
        assert "Agent" in captured["disallowed_tools"]

    @pytest.mark.asyncio
    async def test_a_fan_out_session_keeps_dispatch(self, tmp_path):
        """The working phase must be able to spawn its team, exactly as before."""
        captured = await _capture_options(tmp_path, lambda _d: {"hive-worker": MagicMock()})

        assert "disallowed_tools" not in captured
        assert captured["agents"]

    @pytest.mark.asyncio
    async def test_a_loader_returning_nothing_still_keeps_dispatch(self, tmp_path):
        """claudetm stands down when the project defines its own worker.

        The definitions then come from the CLI via ``setting_sources``, so an
        empty dict must not be read as "this phase may not fan out" — only the
        absence of a loader means that.
        """
        captured = await _capture_options(tmp_path, lambda _d: {})

        assert "disallowed_tools" not in captured
        assert captured["agents"] is None
