"""Real-SDK smoke test — opt-in only.

This test is skipped by default.  To run it you need:

1. A valid `~/.claude/.credentials.json` with a live OAuth token.
2. The `CLAUDETM_REAL_SDK=1` environment variable.

Run with:
    CLAUDETM_REAL_SDK=1 pytest tests/integration/test_real_sdk_smoke.py -v

The test verifies that the *actual* Claude Agent SDK end-to-end path works —
something the `MockClaudeAgentSDK` suite cannot exercise.  It is intentionally
small (one planning-phase invocation) so that it runs in under 60 s on a live
connection and costs minimal tokens.

Markers:
    real_sdk  — requires CLAUDETM_REAL_SDK=1 env var
    integration — requires external services
    slow — may take 30-60 s on a real API call
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Guard: skip the entire module unless the opt-in variable is set.
# This prevents accidental live API calls in CI.
pytestmark = [
    pytest.mark.real_sdk,
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        not os.environ.get("CLAUDETM_REAL_SDK"),
        reason=(
            "Real SDK smoke test skipped. "
            "Set CLAUDETM_REAL_SDK=1 and provide valid credentials to run."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def credentials_path() -> Path:
    """Return the default credentials path; skip if missing."""
    creds = Path.home() / ".claude" / ".credentials.json"
    if not creds.exists():
        pytest.skip(f"Credentials file not found at {creds}")
    return creds


@pytest.fixture
def access_token(credentials_path: Path) -> str:
    """Extract the access token from credentials; skip if not loadable."""
    import json

    try:
        data = json.loads(credentials_path.read_text())
        token: str | None = data.get("claudeAiOauth", {}).get("accessToken")
        if not token:
            pytest.skip("No accessToken found in credentials file")
        return token  # guaranteed non-None after the skip guard
    except (json.JSONDecodeError, KeyError) as exc:
        pytest.skip(f"Could not read credentials: {exc}")
    return ""  # unreachable; satisfies mypy


@pytest.fixture
def agent_wrapper(access_token: str, tmp_path: Path):
    """Create a real AgentWrapper backed by live credentials."""
    try:
        from claude_task_master.core.agent import AgentWrapper, ModelType
    except ImportError as exc:
        pytest.skip(f"claude_task_master not importable: {exc}")

    return AgentWrapper(
        access_token=access_token,
        model=ModelType.HAIKU,  # cheapest / fastest for a smoke test
        working_dir=str(tmp_path),
        enable_safety_hooks=False,  # no hooks needed for a smoke test
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRealSDKSmoke:
    """Smoke tests exercising the live Claude Agent SDK end-to-end path."""

    def test_agent_wrapper_instantiates_with_live_creds(self, agent_wrapper) -> None:
        """AgentWrapper must instantiate without raising against live creds."""
        from claude_task_master.core.agent import AgentWrapper

        assert isinstance(agent_wrapper, AgentWrapper)

    def test_planning_phase_returns_dict(self, agent_wrapper) -> None:
        """run_planning_phase must return a dict with 'plan' and 'criteria' keys.

        This is the canonical entry point used by Planner.create_plan() and is
        the minimal surface area for an end-to-end smoke test.
        The goal is deliberately trivial to minimise token usage.
        """
        result = agent_wrapper.run_planning_phase(
            goal="Add a Python file that prints 'hello world'",
        )

        assert isinstance(result, dict), "run_planning_phase must return a dict"
        assert "plan" in result, "Result must contain a 'plan' key"
        assert "criteria" in result, "Result must contain a 'criteria' key"
        assert isinstance(result["plan"], str), "'plan' value must be a string"
        assert len(result["plan"]) > 0, "'plan' must be non-empty"

    def test_planning_phase_plan_contains_tasks(self, agent_wrapper) -> None:
        """The live planning response must contain at least one checkbox task."""
        result = agent_wrapper.run_planning_phase(
            goal="Add a Python file that prints 'hello world'",
        )

        plan = result.get("plan", "")
        # Expect at least one markdown checkbox line.
        has_task = "- [ ]" in plan or "- [x]" in plan
        assert has_task, f"Plan must contain at least one task checkbox; got:\n{plan[:500]}"
