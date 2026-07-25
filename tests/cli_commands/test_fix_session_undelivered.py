"""Tests for the undelivered-fix guard on the `merge-pr`/`fix-pr` CLI path.

The same defect the orchestrator's review stage had: `run_fix_session` posted
the comment replies — which resolve the threads on GitHub — straight after the
agent session, without checking the fix had actually been committed and pushed.
A session killed mid-turn therefore reported a handled review for work still
sitting in the working tree, and the merge loop proceeded on the previous
push's green CI.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.cli_commands.fix_session import (
    fix_session_undelivered_reason,
    pending_changes_summary,
    run_fix_session,
)

_MODULE = "claude_task_master.cli_commands.fix_session"


def _mocks() -> tuple:
    agent = MagicMock()
    agent.run_work_session.return_value = {"output": "done", "success": True}
    github_client = MagicMock()
    state_manager = MagicMock()
    state_manager.get_pr_dir.return_value = "/tmp/pr-123"
    pr_context = MagicMock()
    pr_context.save_pr_comments.return_value = 2
    return agent, github_client, state_manager, pr_context


class TestRunFixSessionDelivery:
    """Replies are posted only for a fix that reached the PR."""

    def test_undelivered_fix_does_not_resolve_threads(self) -> None:
        agent, github_client, state_manager, pr_context = _mocks()

        with patch(
            f"{_MODULE}.fix_session_undelivered_reason",
            return_value="uncommitted changes left behind",
        ):
            result = run_fix_session(
                agent,
                github_client,
                state_manager,
                pr_context,
                pr_number=123,
                ci_failed=False,
                comment_count=2,
            )

        assert result is False
        pr_context.post_comment_replies.assert_not_called()

    def test_delivered_fix_resolves_threads(self) -> None:
        agent, github_client, state_manager, pr_context = _mocks()

        with patch(f"{_MODULE}.fix_session_undelivered_reason", return_value=None):
            result = run_fix_session(
                agent,
                github_client,
                state_manager,
                pr_context,
                pr_number=123,
                ci_failed=False,
                comment_count=2,
            )

        assert result is True
        pr_context.post_comment_replies.assert_called_once_with(123)


class TestFixSessionUndeliveredReason:
    """The probe, including the fail-open cases."""

    @pytest.fixture(autouse=True)
    def _no_ambient_git(self):
        """Never let the developer's real repository answer these."""
        yield

    def test_dirty_tree(self) -> None:
        with patch(f"{_MODULE}.subprocess.run") as run:
            run.return_value = MagicMock(stdout=" M a.py\n")
            assert fix_session_undelivered_reason("feat/x") is not None

    def test_unpushed_commits(self) -> None:
        outputs = {"status": "", "fetch": "", "rev-list": "3"}

        def _run(cmd, **kwargs):
            key = next((k for k in outputs if k in cmd), None)
            return MagicMock(stdout=outputs.get(key or "", ""))

        with patch(f"{_MODULE}.subprocess.run", side_effect=_run):
            reason = fix_session_undelivered_reason("feat/x")

        assert reason is not None and "push" in reason

    def test_clean_and_pushed(self) -> None:
        with patch(f"{_MODULE}.subprocess.run") as run:
            run.return_value = MagicMock(stdout="")
            assert fix_session_undelivered_reason("feat/x") is None

    def test_unreadable_repo_is_not_a_violation(self) -> None:
        with patch(f"{_MODULE}.subprocess.run", side_effect=OSError("no git")):
            assert fix_session_undelivered_reason("feat/x") is None


class TestPendingChangesSummary:
    """Used by the merge guard — must fail open, never block on an unknown."""

    def test_lists_pending_files(self) -> None:
        with patch(f"{_MODULE}.subprocess.run") as run:
            run.return_value = MagicMock(stdout=" M a.py\n?? b.py\n")
            assert pending_changes_summary() == " M a.py\n?? b.py"

    def test_clean_is_empty(self) -> None:
        with patch(f"{_MODULE}.subprocess.run") as run:
            run.return_value = MagicMock(stdout="\n")
            assert pending_changes_summary() == ""

    def test_unreadable_is_empty(self) -> None:
        with patch(f"{_MODULE}.subprocess.run", side_effect=OSError("no git")):
            assert pending_changes_summary() == ""

    def test_long_listing_is_truncated(self) -> None:
        with patch(f"{_MODULE}.subprocess.run") as run:
            run.return_value = MagicMock(stdout="\n".join(f" M f{i}.py" for i in range(30)))
            out = pending_changes_summary(max_lines=5)

        assert out.splitlines()[-1] == "... and 25 more"
