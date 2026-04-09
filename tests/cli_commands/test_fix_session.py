"""Tests for fix session logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from claude_task_master.cli_commands.fix_session import (
    get_current_branch,
    run_fix_session,
)


class TestGetCurrentBranch:
    """Tests for get_current_branch function."""

    @patch("claude_task_master.cli_commands.fix_session.subprocess.run")
    def test_returns_branch_name(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="feature/my-branch\n")
        assert get_current_branch() == "feature/my-branch"

    @patch("claude_task_master.cli_commands.fix_session.subprocess.run")
    def test_returns_none_on_empty(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="")
        assert get_current_branch() is None

    @patch("claude_task_master.cli_commands.fix_session.subprocess.run")
    def test_returns_none_on_exception(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = Exception("git not found")
        assert get_current_branch() is None


class TestRunFixSession:
    """Tests for run_fix_session function."""

    def _make_mocks(self) -> tuple:
        agent = MagicMock()
        agent.run_work_session.return_value = {"output": "done", "success": True}
        github_client = MagicMock()
        state_manager = MagicMock()
        state_manager.get_pr_dir.return_value = "/tmp/pr-123"
        pr_context = MagicMock()
        return agent, github_client, state_manager, pr_context

    def test_returns_false_when_no_actionable_work(self) -> None:
        """Should return False when only non-actionable comments exist."""
        agent, github_client, state_manager, pr_context = self._make_mocks()
        pr_context.save_pr_comments.return_value = 0  # no actionable comments

        result = run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=False, comment_count=3,
        )
        assert result is False
        agent.run_work_session.assert_not_called()

    def test_returns_true_when_ci_failed(self) -> None:
        """Should always run agent when CI failed."""
        agent, github_client, state_manager, pr_context = self._make_mocks()

        result = run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=True, comment_count=0,
        )
        assert result is True
        agent.run_work_session.assert_called_once()

    def test_ci_failed_calls_save_ci_failures(self) -> None:
        """Should download CI failure logs when CI failed."""
        agent, github_client, state_manager, pr_context = self._make_mocks()

        run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=True, comment_count=0,
        )
        pr_context.save_ci_failures.assert_called_once_with(123)

    def test_returns_true_when_has_conflicts(self) -> None:
        """Should run agent when there are merge conflicts."""
        agent, github_client, state_manager, pr_context = self._make_mocks()

        result = run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=False, comment_count=0, has_conflicts=True,
        )
        assert result is True
        agent.run_work_session.assert_called_once()

    def test_returns_true_with_actionable_comments(self) -> None:
        """Should run agent when there are actionable comments."""
        agent, github_client, state_manager, pr_context = self._make_mocks()
        pr_context.save_pr_comments.return_value = 2

        result = run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=False, comment_count=2,
        )
        assert result is True
        agent.run_work_session.assert_called_once()

    def test_posts_comment_replies_after_agent_runs(self) -> None:
        """Should post comment replies after agent addresses comments."""
        agent, github_client, state_manager, pr_context = self._make_mocks()
        pr_context.save_pr_comments.return_value = 2

        run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=False, comment_count=2,
        )
        pr_context.post_comment_replies.assert_called_once_with(123)

    def test_no_comment_replies_when_no_comments(self) -> None:
        """Should not post comment replies when only CI was fixed."""
        agent, github_client, state_manager, pr_context = self._make_mocks()

        run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=True, comment_count=0,
        )
        pr_context.post_comment_replies.assert_not_called()

    def test_agent_called_with_create_pr_false(self) -> None:
        """Agent should not create a new PR - it's fixing an existing one."""
        agent, github_client, state_manager, pr_context = self._make_mocks()

        run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=True, comment_count=0,
        )
        call_kwargs = agent.run_work_session.call_args[1]
        assert call_kwargs["create_pr"] is False

    def test_returns_false_no_ci_no_comments_no_conflicts(self) -> None:
        """Should return False when nothing needs fixing."""
        agent, github_client, state_manager, pr_context = self._make_mocks()

        result = run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=False, comment_count=0, has_conflicts=False,
        )
        assert result is False
        agent.run_work_session.assert_not_called()

    def test_combined_ci_and_comments(self) -> None:
        """Should handle both CI failures and comments in one session."""
        agent, github_client, state_manager, pr_context = self._make_mocks()
        pr_context.save_pr_comments.return_value = 1

        result = run_fix_session(
            agent, github_client, state_manager, pr_context,
            pr_number=123, ci_failed=True, comment_count=1,
        )
        assert result is True
        pr_context.save_ci_failures.assert_called_once()
        pr_context.save_pr_comments.assert_called_once()
        agent.run_work_session.assert_called_once()
        # Task description should mention both CI and comments
        call_kwargs = agent.run_work_session.call_args[1]
        assert "CI Failures" in call_kwargs["task_description"]
        assert "Review Comments" in call_kwargs["task_description"]
