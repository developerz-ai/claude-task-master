"""Regressions for the token blow-up that arrived with hive fan-out.

Subagents multiply everything: a session that fans out pays N cold starts, and
anything that makes such a session re-run pays them again. Each test here pins
one defect that was found by measuring real runs after fan-out shipped.
"""

from __future__ import annotations

import pytest

from claude_task_master.core.agent_phase_generation import _AgentPhaseGenerationMixin
from claude_task_master.core.context_accumulator import (
    MAX_CONTEXT_CHARS,
    truncate_context_for_prompt,
)
from claude_task_master.core.hive import (
    fan_out_enabled,
    hive_worker_effort,
    hive_worker_max_turns,
)
from claude_task_master.core.prompts_verification import build_context_extraction_prompt
from claude_task_master.core.subagents import build_builtin_agents, parse_agent_frontmatter


class TestAgentsRegisteredOnlyWhereFanOutIsAllowed:
    """Regression: hive-worker rode along on every query, in every phase.

    ``get_agents_for_working_dir`` was wired into the phase executor once and
    used unconditionally, so ``--no-parallel`` removed the fan-out brief but
    left the worker definition registered and the Agent tool available; and
    planning, verification, release checks, learnings extraction and every
    push-only fix session carried the worker contract and could act on it. A
    review-fix session was observed dispatching hive-workers this way.
    """

    class _Phases(_AgentPhaseGenerationMixin):
        def __init__(self) -> None:
            self.get_agents_func = object()

    def test_no_agents_when_fan_out_is_off(self) -> None:
        assert self._Phases().agents_for(False) is None

    def test_agents_when_fan_out_is_on(self) -> None:
        phases = self._Phases()
        assert phases.agents_for(True) is phases.get_agents_func

    @pytest.mark.parametrize(
        ("parallel", "push_only", "expected"),
        [
            (True, False, True),  # a normal work session
            (True, True, False),  # a fix session: documented as never fanning out
            (False, False, False),  # --no-parallel
            (False, True, False),
        ],
    )
    def test_fan_out_predicate(self, parallel: bool, push_only: bool, expected: bool) -> None:
        assert fan_out_enabled(parallel, push_only) is expected


@pytest.fixture
def default_hive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert against claudetm's defaults, not the developer's shell.

    These knobs are read from the environment at call time, so a valid
    ``CLAUDETM_HIVE_WORKER_MAX_TURNS`` or ``CLAUDETM_HIVE_WORKER_EFFORT`` set
    outside the test run would fail an assertion about a correct implementation.
    """
    for name in (
        "CLAUDETM_HIVE_WORKER_MAX_TURNS",
        "CLAUDETM_HIVE_WORKER_EFFORT",
        "CLAUDETM_HIVE_MAX_PARALLEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("default_hive_env")
class TestWorkerDispatchIsForegroundAndBounded:
    """Regression: rules that cost a whole task when broken lived in prose only."""

    def test_workers_cannot_be_backgrounded(self) -> None:
        """A worker still writing after the lead's turn ends re-runs the task.

        Measured across real runs: 39 of 210 hive-worker dispatches were
        explicitly backgrounded and 18 more omitted the parameter, which the
        Agent tool defaults to background — 27% of dispatches ignoring the
        brief's most expensive rule.
        """
        assert build_builtin_agents()["hive-worker"].background is False

    def test_workers_cannot_spawn_workers(self) -> None:
        """Recursive fan-out escapes max_parallel and the exclusive file sets."""
        disallowed = build_builtin_agents()["hive-worker"].disallowedTools or []
        assert "Task" in disallowed
        assert "Agent" in disallowed

    def test_the_session_has_room_for_a_team(self) -> None:
        """Turns are charged against ONE session cap, lead and workers together.

        Regression: the cap was 400, written for a soloist, while each worker
        carries 200 — so a lead plus two busy workers could end the session in
        ``error_max_turns`` with nothing committed, re-running the whole
        fanned-out task. The cap now has room for a real team; workers are not
        rationed to fit inside a number written for one agent, because a worker
        that stops mid-piece hands the lead back work that was nearly done.
        """
        from claude_task_master.core.agent_query import MAX_TURNS

        assert MAX_TURNS is not None
        assert hive_worker_max_turns() * 4 <= MAX_TURNS

    def test_workers_keep_a_generous_budget(self) -> None:
        """A worker takes a whole module end to end; 200 is a backstop, not a ration."""
        assert hive_worker_max_turns() == 200

    def test_worker_turn_budget_env_override_still_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDETM_HIVE_WORKER_MAX_TURNS", "321")
        assert hive_worker_max_turns() == 321


@pytest.mark.usefixtures("default_hive_env")
class TestWorkerEffort:
    """Regression: workers inherited the session's effort, i.e. Opus at "max"."""

    def test_default_is_deep_but_not_maximum(self) -> None:
        assert hive_worker_effort() == "high"
        assert build_builtin_agents()["hive-worker"].effort == "high"

    def test_model_tier_is_untouched(self) -> None:
        """Only thinking depth is dialled back — the worker is still on Opus."""
        assert build_builtin_agents()["hive-worker"].model == "inherit"

    def test_inherit_restores_the_old_behaviour(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDETM_HIVE_WORKER_EFFORT", "inherit")
        assert hive_worker_effort() is None

    def test_garbage_does_not_end_a_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDETM_HIVE_WORKER_EFFORT", "banana")
        assert hive_worker_effort() == "high"


class TestAccumulatedContextIsCappedAtTheRead:
    """Regression: the 32k cap had one caller and every prompt bypassed it.

    ``ContextAccumulator.get_context_for_prompt`` applied the cap, but the
    dozen sites that actually build prompts called ``load_context()`` and
    injected the raw file. A real ``context.md`` reached 157 KB — ~39k tokens in
    every session's prompt, re-read from cache on every turn of it.
    """

    def test_state_manager_exposes_a_capped_read(self, tmp_path) -> None:
        from claude_task_master.core.state import StateManager

        manager = StateManager(tmp_path / ".claude-task-master")
        manager.state_dir.mkdir(parents=True, exist_ok=True)
        manager.save_context("x\n" * MAX_CONTEXT_CHARS)

        assert len(manager.load_context()) > MAX_CONTEXT_CHARS
        assert len(manager.load_context_for_prompt()) <= MAX_CONTEXT_CHARS + 200

    def test_short_context_is_passed_through_untouched(self) -> None:
        assert truncate_context_for_prompt("just a little") == "just a little"

    def test_the_tail_is_what_survives(self) -> None:
        context = "\n".join(f"line {i}" for i in range(10_000))
        trimmed = truncate_context_for_prompt(context, 500)
        assert "line 9999" in trimmed
        assert "line 0\n" not in trimmed
        assert "truncated" in trimmed

    def test_zero_is_rejected_rather_than_disabling_the_cap(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            truncate_context_for_prompt("anything", 0)

    def test_one_long_line_does_not_swallow_the_retained_tail(self) -> None:
        """Aligning to the next newline must not throw the context away.

        Regression: the retained slice was cut at its first newline
        unconditionally. When that slice opens with one very long line — a
        pasted diff, a stack trace, a single-line summary — the newline sits
        near the end, and everything before it was dropped, leaving a short
        suffix where the cap promised 32k of recent history.
        """
        context = "prefix\n" + "x" * 5_000 + "\ntail line"
        trimmed = truncate_context_for_prompt(context, 1_000)
        assert len(trimmed) > 900
        assert "tail line" in trimmed


class TestLearningsExtractionReadsTheEnd:
    """Regression: the extractor was shown the head of the session, not the tail."""

    def test_session_output_is_tail_sliced(self) -> None:
        output = "exploration\n" * 2000 + "COMPLETION REPORT: shipped abc123"
        prompt = build_context_extraction_prompt(session_output=output)
        assert "COMPLETION REPORT: shipped abc123" in prompt

    def test_existing_context_is_bounded(self) -> None:
        """Feeding the whole file back made the model restate it, forever."""
        prompt = build_context_extraction_prompt(
            session_output="did a thing",
            existing_context="OLDEST MARKER\n" + ("filler\n" * 20_000) + "NEWEST MARKER",
        )
        assert "NEWEST MARKER" in prompt
        assert "OLDEST MARKER" not in prompt


class TestFrontmatterParserHandlesRealAgentFiles:
    """Regression: the parser mangled the files that make specialists work.

    Every case here left the project's own ``.claude/agents/`` specialist either
    unadvertised or undispatchable, so the lead fell back to a generic worker —
    the opposite of "the project's specialists come first".
    """

    def test_folded_description_is_joined(self) -> None:
        frontmatter, _ = parse_agent_frontmatter(
            "---\nname: x\ndescription: >\n  Use when refactoring\n  a module.\n---\nBody"
        )
        assert frontmatter["description"] == "Use when refactoring a module."

    def test_quotes_are_stripped_from_the_name(self) -> None:
        frontmatter, _ = parse_agent_frontmatter(
            '---\nname: "my-agent"\ndescription: "Use when: refactoring"\n---\nBody'
        )
        assert frontmatter["name"] == "my-agent"
        assert frontmatter["description"] == "Use when: refactoring"

    def test_block_list_tools_are_parsed(self) -> None:
        frontmatter, _ = parse_agent_frontmatter(
            "---\nname: x\ndescription: d\ntools:\n  - Read\n  - Grep\n---\nBody"
        )
        assert frontmatter["tools"] == ["Read", "Grep"]

    def test_nested_keys_do_not_clobber_top_level_ones(self) -> None:
        frontmatter, _ = parse_agent_frontmatter(
            "---\nname: outer\ndescription: d\nmetadata:\n  name: inner\n---\nBody"
        )
        assert frontmatter["name"] == "outer"

    def test_description_no_stays_a_string(self) -> None:
        """`description: no` became False, and the agent was dropped as empty."""
        frontmatter, _ = parse_agent_frontmatter("---\nname: x\ndescription: no\n---\nBody")
        assert frontmatter["description"] == "no"

    def test_missing_trailing_newline_still_parses(self) -> None:
        frontmatter, prompt = parse_agent_frontmatter("---\nname: x\ndescription: d\n---")
        assert frontmatter["name"] == "x"
        assert prompt == ""

    def test_boolean_max_turns_does_not_become_one_turn(self, tmp_path) -> None:
        """`max_turns: yes` parsed to True, then int(True) == 1 turn."""
        from claude_task_master.core.subagents import load_agents_from_directory

        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "a.md").write_text(
            "---\nname: a\ndescription: d\nmax_turns: yes\n---\n\nPrompt.\n"
        )
        agents = load_agents_from_directory(str(tmp_path))
        assert agents["a"].maxTurns == hive_worker_max_turns()
