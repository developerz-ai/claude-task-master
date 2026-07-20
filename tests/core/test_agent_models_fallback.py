"""Tests for fallback chain, effort routing, and tag parsing integration.

This module closes coverage gaps in the agent-lifecycle slice by testing
the *integration* of the routing components that were implemented separately:

- chain  : MODEL_FALLBACK_MAP / get_fallback_chain used by _run_query_with_retry
- effort : MODEL_EFFORT_MAP used by _execute_query to pass effort= to the SDK
- tag    : parse_task_complexity anchoring / last-match used for model routing
- SIGINT : signal-handler → is_cancellation_requested() → orchestrator exit 2
"""

from __future__ import annotations

import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.agent_models import (
    MODEL_EFFORT_MAP,
    MODEL_FALLBACK_MAP,
    ModelType,
    TaskComplexity,
    get_fallback_chain,
    parse_task_complexity,
)

# =============================================================================
# Routing table integrity (chain + effort + tag combined)
# =============================================================================


class TestRoutingTableIntegrity:
    """Every complexity tag produces a model that has an effort level."""

    @pytest.mark.parametrize(
        "tag,expected_complexity,expected_model,expected_effort",
        [
            ("`[coding]`", TaskComplexity.CODING, ModelType.OPUS, "max"),
            ("`[quick]`", TaskComplexity.QUICK, ModelType.HAIKU, "low"),
            ("`[general]`", TaskComplexity.GENERAL, ModelType.SONNET, "medium"),
            ("`[debugging-qa]`", TaskComplexity.DEBUGGING_QA, ModelType.SONNET_1M, "high"),
        ],
    )
    def test_tag_routes_to_model_with_effort(
        self,
        tag: str,
        expected_complexity: TaskComplexity,
        expected_model: ModelType,
        expected_effort: str,
    ):
        """Tag → complexity → model → effort forms an unbroken chain."""
        task = f"{tag} Do some work"
        complexity, _ = parse_task_complexity(task)
        assert complexity == expected_complexity

        model = TaskComplexity.get_model_for_complexity(complexity)
        assert model == expected_model

        effort = MODEL_EFFORT_MAP[model]
        assert effort == expected_effort

    def test_every_model_in_fallback_chains_has_effort(self):
        """No model that appears as a fallback target lacks an effort level."""
        all_fallback_targets = set(MODEL_FALLBACK_MAP.values())
        for model in all_fallback_targets:
            assert model in MODEL_EFFORT_MAP, (
                f"{model} appears as a fallback target but has no entry in MODEL_EFFORT_MAP"
            )

    def test_every_complexity_model_has_effort(self):
        """Every model that a complexity routes to has an effort level."""
        for complexity in TaskComplexity:
            model = TaskComplexity.get_model_for_complexity(complexity)
            assert model in MODEL_EFFORT_MAP

    def test_fable_not_a_complexity_but_has_max_effort(self):
        """FABLE is not a complexity value, but MODEL_EFFORT_MAP gives it 'max'."""
        fable_values = {c.value for c in TaskComplexity}
        assert "fable" not in fable_values  # confirms no complexity routes to FABLE

        # Still must have an effort level — FABLE users opt in explicitly
        assert MODEL_EFFORT_MAP[ModelType.FABLE] == "max"


# =============================================================================
# Fallback chain correctness (spot-checks + invariants)
# =============================================================================


class TestFallbackChainCorrectness:
    """get_fallback_chain builds cycle-guarded chains for every starting model."""

    def test_fable_full_chain(self):
        """FABLE walks the documented chain: Opus → Sonnet → Haiku."""
        chain = get_fallback_chain(ModelType.FABLE)
        assert chain == [ModelType.OPUS, ModelType.SONNET, ModelType.HAIKU]

    def test_opus_chain(self):
        """OPUS falls back to Sonnet then Haiku."""
        assert get_fallback_chain(ModelType.OPUS) == [ModelType.SONNET, ModelType.HAIKU]

    def test_sonnet_1m_chain(self):
        """SONNET_1M falls back to Haiku → Sonnet (Haiku↔Sonnet cycle then cut)."""
        chain = get_fallback_chain(ModelType.SONNET_1M)
        assert chain == [ModelType.HAIKU, ModelType.SONNET]

    def test_haiku_sonnet_cycle_cut(self):
        """HAIKU→SONNET back-edge is detected and the cycle stops at Sonnet."""
        haiku_chain = get_fallback_chain(ModelType.HAIKU)
        # Sonnet is reachable, but Haiku must NOT reappear
        assert ModelType.HAIKU not in haiku_chain
        assert ModelType.SONNET in haiku_chain

    def test_sonnet_haiku_cycle_cut(self):
        """SONNET→HAIKU back-edge is detected and the cycle stops at Haiku."""
        sonnet_chain = get_fallback_chain(ModelType.SONNET)
        assert ModelType.SONNET not in sonnet_chain
        assert ModelType.HAIKU in sonnet_chain

    def test_no_starting_model_in_its_own_chain(self):
        """The starting model never appears in its own fallback chain."""
        for model in ModelType:
            assert model not in get_fallback_chain(model)

    def test_no_duplicates_in_any_chain(self):
        """The cycle guard guarantees no model appears twice."""
        for model in ModelType:
            chain = get_fallback_chain(model)
            assert len(chain) == len(set(chain)), (
                f"Duplicate in fallback chain for {model}: {chain}"
            )

    def test_chain_first_hop_matches_fallback_map(self):
        """The first chain element matches the raw MODEL_FALLBACK_MAP entry."""
        for model, expected_first in MODEL_FALLBACK_MAP.items():
            chain = get_fallback_chain(model)
            assert chain[0] == expected_first


# =============================================================================
# Effort routing via _execute_query (integration with AgentQueryExecutor)
# =============================================================================


class TestEffortPassedToOptions:
    """_execute_query looks up MODEL_EFFORT_MAP and passes effort= to options."""

    def _make_agent(self, temp_dir, model: ModelType):
        """AgentWrapper with fast retry config and mocked SDK."""
        from claude_task_master.core.agent import AgentWrapper
        from claude_task_master.core.rate_limit import RateLimitConfig

        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="tok",
                model=model,
                working_dir=str(temp_dir),
                rate_limit_config=RateLimitConfig(
                    max_retries=0, initial_backoff=0.01, max_backoff=0.01
                ),
            )
        return agent

    @staticmethod
    def _capture_options(store: list[dict]):
        """Stub options_class that records kwargs passed to it."""

        def capture(**kwargs):
            store.append(kwargs)
            return MagicMock()

        return capture

    @pytest.mark.asyncio
    async def test_haiku_gets_low_effort(self, temp_dir):
        """HAIKU model → options effort='low'."""
        agent = self._make_agent(temp_dir, ModelType.HAIKU)
        calls: list[dict] = []
        agent.options_class = self._capture_options(calls)
        agent._query_executor.options_class = agent.options_class

        async def quick_gen(*a, **kw):
            yield MagicMock(content=None)

        agent.query = quick_gen
        agent._query_executor.query = quick_gen

        with patch(
            "claude_task_master.core.agent.get_agents_for_working_dir",
            return_value={},
        ):
            await agent._run_query("p", [], model_override=ModelType.HAIKU)
        assert calls[0]["effort"] == "low"

    @pytest.mark.asyncio
    async def test_sonnet_1m_gets_high_effort(self, temp_dir):
        """SONNET_1M model → options effort='high'."""
        agent = self._make_agent(temp_dir, ModelType.SONNET_1M)
        calls: list[dict] = []
        agent.options_class = self._capture_options(calls)
        agent._query_executor.options_class = agent.options_class

        async def quick_gen(*a, **kw):
            yield MagicMock(content=None)

        agent.query = quick_gen
        agent._query_executor.query = quick_gen

        with patch(
            "claude_task_master.core.agent.get_agents_for_working_dir",
            return_value={},
        ):
            await agent._run_query("p", [], model_override=ModelType.SONNET_1M)
        assert calls[0]["effort"] == "high"


# =============================================================================
# Multi-hop fallback in _run_query_with_retry
# =============================================================================


class TestMultiHopFallback:
    """_run_query_with_retry walks the full chain on successive ModelUnavailableError."""

    def _make_agent(self, temp_dir):
        """AgentWrapper backed by FABLE with no transient retries."""
        from claude_task_master.core.agent import AgentWrapper
        from claude_task_master.core.rate_limit import RateLimitConfig

        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="tok",
                model=ModelType.FABLE,
                working_dir=str(temp_dir),
                rate_limit_config=RateLimitConfig(
                    max_retries=0, initial_backoff=0.01, max_backoff=0.01
                ),
            )
        return agent

    @pytest.mark.asyncio
    async def test_fable_falls_back_past_first_sdk_hop(self, temp_dir):
        """FABLE unavailable + OPUS (SDK auto-fallback) skipped → lands on SONNET.

        The SDK's ``fallback_model`` already tries OPUS automatically; the
        retry loop seeds it as ``attempted`` so the *next* manual hop is SONNET
        (not a redundant OPUS re-try).
        """
        agent = self._make_agent(temp_dir)
        options_calls: list[dict] = []

        def capture_options(**kwargs):
            options_calls.append(kwargs)
            return MagicMock()

        agent.options_class = capture_options
        agent._query_executor.options_class = capture_options

        call_count = 0

        async def fail_once_then_succeed(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("model: claude-fable-5 not_found_error")
            yield MagicMock(content=None)

        agent.query = fail_once_then_succeed
        agent._query_executor.query = fail_once_then_succeed

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "claude_task_master.core.agent.get_agents_for_working_dir",
                return_value={},
            ),
        ):
            await agent._run_query("p", [], model_override=ModelType.FABLE)

        assert call_count == 2
        assert options_calls[0]["model"] == agent._get_model_name(ModelType.FABLE)
        # Second attempt skips OPUS (SDK auto-fallback already seeded) → SONNET
        assert options_calls[1]["model"] == agent._get_model_name(ModelType.SONNET)

    @pytest.mark.asyncio
    async def test_model_unavailable_errors_do_not_consume_failure_budget(self, temp_dir):
        """ModelUnavailableError must not increment the transient-failure counter."""
        from claude_task_master.core.agent_exceptions import ModelUnavailableError

        agent = self._make_agent(temp_dir)

        async def always_unavailable(*a, **kw):
            raise Exception("model not found")
            yield  # pragma: no cover

        agent.query = always_unavailable
        agent._query_executor.query = always_unavailable

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "claude_task_master.core.agent.get_agents_for_working_dir",
                return_value={},
            ),
        ):
            with pytest.raises(ModelUnavailableError):
                await agent._run_query("p", [], model_override=ModelType.FABLE)

        # Failure budget must be clean — zero transient failures charged
        assert agent._query_executor._consecutive_failures == 0


# =============================================================================
# Tag anchoring edge cases
# =============================================================================


class TestTagAnchoringEdgeCases:
    """parse_task_complexity anchors leading/trailing tags over mid-prose ones."""

    def test_leading_quick_beats_mid_prose_coding(self):
        """`[quick]` at start wins over `[coding]` buried in prose."""
        task = "`[quick]` fix typo, avoid `[coding]` complexity"
        complexity, cleaned = parse_task_complexity(task)
        assert complexity == TaskComplexity.QUICK
        # Only the winning leading tag is stripped; prose mention survives
        assert "`[coding]`" in cleaned

    def test_trailing_coding_beats_mid_prose_general(self):
        """`[coding]` trailing anchor beats an interior `[general]` mention."""
        task = "implement auth (not just `[general]` work) `[coding]`"
        complexity, cleaned = parse_task_complexity(task)
        assert complexity == TaskComplexity.CODING
        # Mid-prose `[general]` must survive since only the winner is stripped
        assert "`[general]`" in cleaned

    def test_last_wins_when_none_anchored(self):
        """When no tag is anchored, the last occurrence wins."""
        task = "do `[general]` work then more `[coding]` in the middle"
        complexity, _ = parse_task_complexity(task)
        # Neither tag is anchored (non-empty before and after), last → CODING
        assert complexity == TaskComplexity.CODING

    def test_stripped_tag_absent_in_cleaned(self):
        """The winning tag is absent from the cleaned description."""
        task = "`[quick]` Update the README"
        _, cleaned = parse_task_complexity(task)
        assert "[quick]" not in cleaned
        assert "Update the README" in cleaned

    def test_default_to_coding_when_no_tag(self):
        """No tag → defaults to CODING (prefer smarter model)."""
        complexity, cleaned = parse_task_complexity("Implement feature X")
        assert complexity == TaskComplexity.CODING
        assert cleaned == "Implement feature X"

    def test_debugging_qa_bare_tag(self):
        """Bare [debugging-qa] without backticks is also recognised."""
        complexity, cleaned = parse_task_complexity("[debugging-qa] Trace CI failure")
        assert complexity == TaskComplexity.DEBUGGING_QA
        assert "[debugging-qa]" not in cleaned


# =============================================================================
# SIGINT mid-query → is_cancellation_requested → exit 2 path
# =============================================================================


class TestSIGINTCancellationPath:
    """SIGINT → ShutdownManager → is_cancellation_requested() → orchestrator exit 2."""

    def setup_method(self):
        """Isolate the global shutdown manager for each test."""
        from claude_task_master.core.shutdown import get_shutdown_manager, reset_shutdown

        self._mgr = get_shutdown_manager()
        self._mgr.set_durable_stop_check(None)
        reset_shutdown()

    def teardown_method(self):
        """Always restore clean shutdown state."""
        from claude_task_master.core.shutdown import reset_shutdown

        self._mgr.set_durable_stop_check(None)
        reset_shutdown()

    def test_signal_handler_sets_sigint_reason(self):
        """Calling _signal_handler(SIGINT) records 'SIGINT' as the shutdown reason."""
        mgr = self._mgr
        mgr._signal_handler(signal.SIGINT, None)
        assert mgr.shutdown_requested
        assert mgr.shutdown_reason == "SIGINT"

    def test_shutdown_after_sigint_makes_cancellation_requested(self):
        """After SIGINT, is_cancellation_requested() returns True.

        This is the precise check the orchestrator's main loop polls each cycle:
        is_cancellation_requested() → True → _handle_pause() → return 2.
        """
        from claude_task_master.core.key_listener import is_cancellation_requested

        # Simulate the signal handler path
        self._mgr.request_shutdown("SIGINT")

        assert is_cancellation_requested() is True

    def test_sigint_via_registered_handler(self):
        """Registering handlers and then firing SIGINT marks shutdown requested."""
        mgr = self._mgr

        # Register in-process handlers (safe from main thread in tests)
        with patch("signal.signal") as mock_signal:
            mock_signal.return_value = signal.SIG_DFL
            mgr.register()

        # Simulate the OS calling our handler directly
        mgr._signal_handler(signal.SIGINT, None)

        assert mgr.shutdown_requested
        assert mgr.shutdown_reason == "SIGINT"

        # Cleanup
        mgr.unregister()
        from claude_task_master.core.shutdown import reset_shutdown

        reset_shutdown()

    def test_reason_reset_before_next_query(self):
        """After reset(), is_cancellation_requested() returns False again."""
        from claude_task_master.core.key_listener import is_cancellation_requested
        from claude_task_master.core.shutdown import reset_shutdown

        self._mgr.request_shutdown("SIGINT")
        assert is_cancellation_requested() is True

        reset_shutdown()
        assert is_cancellation_requested() is False

    def test_orchestrator_returns_exit_2_on_cancellation(self, tmp_path):
        """When cancellation is detected, orchestrator.run() returns 2.

        This is an end-to-end check of the SIGINT → exit-2 path without
        delivering an actual OS signal: we patch is_cancellation_requested()
        to return True (exactly what the signal handler produces) and assert
        the return code is 2, matching the documented exit codes.
        """
        from unittest.mock import MagicMock as _MM

        from claude_task_master.core.orchestrator import WorkLoopOrchestrator

        state_mgr = _MM()
        state = _MM()
        state.status = "idle"
        state.session_count = 0
        state.workflow_stage = "idle"
        state.ci_poll_start_time = None
        state.options = _MM()
        state.options.max_sessions = 10
        state.options.auto_merge = False
        state.options.pr_per_task = False
        state.current_task_index = 0
        state_mgr.load_state.return_value = state
        state_mgr.state_dir = tmp_path / ".claude-task-master"
        state_mgr.state_dir.mkdir()
        state_mgr.load_goal.return_value = "test goal"
        state_mgr.exists.return_value = True
        state_mgr.save_state_merged = _MM()

        orchestrator = WorkLoopOrchestrator(
            agent=_MM(),
            state_manager=state_mgr,
            planner=_MM(),
        )

        # Inject a mock task_runner that reports pending tasks so the main
        # loop is entered (where is_cancellation_requested is checked).
        mock_task_runner = _MM()
        mock_task_runner.is_all_complete.return_value = False
        orchestrator._task_runner = mock_task_runner

        with (
            patch(
                "claude_task_master.core.orchestrator_loop.is_cancellation_requested",
                return_value=True,
            ),
            patch(
                "claude_task_master.core.orchestrator_loop.get_cancellation_reason",
                return_value="SIGINT",
            ),
            patch("claude_task_master.core.orchestrator_loop.start_listening"),
            patch("claude_task_master.core.orchestrator_loop.stop_listening"),
            patch("claude_task_master.core.orchestrator_loop.register_handlers"),
            patch("claude_task_master.core.orchestrator_loop.unregister_handlers"),
            patch("claude_task_master.core.orchestrator_loop.reset_shutdown"),
            patch("claude_task_master.core.orchestrator_loop.set_durable_stop_check"),
            patch("claude_task_master.core.orchestrator_loop.console"),
        ):
            result = orchestrator.run()

        assert result == 2
