"""Tests for GitHub client utility methods - models, helpers, and internal utilities."""

import json
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.client import (
    GitHubError,
    PRStatus,
    WorkflowRun,
)

# =============================================================================
# WorkflowRun Model Tests
# =============================================================================


class TestWorkflowRunModel:
    """Tests for the WorkflowRun Pydantic model."""

    def test_workflow_run_creation_with_all_fields(self):
        """Test creating WorkflowRun with all required fields."""
        run = WorkflowRun(
            id=123,
            name="CI",
            status="completed",
            conclusion="success",
            url="https://github.com/owner/repo/actions/runs/123",
            head_branch="main",
            event="push",
        )
        assert run.id == 123
        assert run.name == "CI"
        assert run.status == "completed"
        assert run.conclusion == "success"
        assert run.url == "https://github.com/owner/repo/actions/runs/123"
        assert run.head_branch == "main"
        assert run.event == "push"

    def test_workflow_run_with_null_conclusion(self):
        """Test creating WorkflowRun with null conclusion (in progress)."""
        run = WorkflowRun(
            id=456,
            name="Build",
            status="in_progress",
            conclusion=None,
            url="https://github.com/owner/repo/actions/runs/456",
            head_branch="feature",
            event="pull_request",
        )
        assert run.conclusion is None
        assert run.status == "in_progress"

    def test_workflow_run_model_dump(self):
        """Test that model can be serialized to dict."""
        run = WorkflowRun(
            id=789,
            name="Deploy",
            status="queued",
            conclusion=None,
            url="https://github.com/owner/repo/actions/runs/789",
            head_branch="release",
            event="workflow_dispatch",
        )
        data = run.model_dump()
        assert data["id"] == 789
        assert data["name"] == "Deploy"
        assert data["status"] == "queued"
        assert data["conclusion"] is None
        assert data["event"] == "workflow_dispatch"

    def test_workflow_run_validation_missing_id(self):
        """Test that missing id raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            WorkflowRun(  # type: ignore[call-arg]
                name="CI",
                status="completed",
                conclusion="success",
                url="https://example.com",
                head_branch="main",
                event="push",
            )
        assert "id" in str(exc_info.value)

    def test_workflow_run_validation_missing_name(self):
        """Test that missing name raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            WorkflowRun(  # type: ignore[call-arg]
                id=123,
                status="completed",
                conclusion="success",
                url="https://example.com",
                head_branch="main",
                event="push",
            )
        assert "name" in str(exc_info.value)

    def test_workflow_run_validation_invalid_id_type(self):
        """Test that invalid id type raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            WorkflowRun(
                id="not-a-number",  # type: ignore[arg-type]
                name="CI",
                status="completed",
                conclusion="success",
                url="https://example.com",
                head_branch="main",
                event="push",
            )
        assert "id" in str(exc_info.value)

    def test_workflow_run_various_statuses(self):
        """Test WorkflowRun with various status values."""
        statuses = ["queued", "in_progress", "completed"]
        for status in statuses:
            run = WorkflowRun(
                id=1,
                name="Test",
                status=status,
                conclusion=None if status != "completed" else "success",
                url="https://example.com",
                head_branch="main",
                event="push",
            )
            assert run.status == status

    def test_workflow_run_various_conclusions(self):
        """Test WorkflowRun with various conclusion values."""
        conclusions = ["success", "failure", "cancelled", "skipped", "timed_out", None]
        for conclusion in conclusions:
            run = WorkflowRun(
                id=1,
                name="Test",
                status="completed" if conclusion else "in_progress",
                conclusion=conclusion,
                url="https://example.com",
                head_branch="main",
                event="push",
            )
            assert run.conclusion == conclusion

    def test_workflow_run_various_events(self):
        """Test WorkflowRun with various event types."""
        events = ["push", "pull_request", "workflow_dispatch", "schedule", "release"]
        for event in events:
            run = WorkflowRun(
                id=1,
                name="Test",
                status="completed",
                conclusion="success",
                url="https://example.com",
                head_branch="main",
                event=event,
            )
            assert run.event == event


# =============================================================================
# GitHubClient.get_pr_for_current_branch Tests
# =============================================================================


class TestGitHubClientGetPRForCurrentBranch:
    """Tests for get_pr_for_current_branch utility method."""

    def test_get_pr_for_current_branch_success(self, github_client):
        """Test successful retrieval of PR for current branch."""
        response = {"number": 42}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            result = github_client.get_pr_for_current_branch()

            assert result == 42
            # Verify command arguments
            call_args = mock_run.call_args[0][0]
            assert "gh" in call_args
            assert "pr" in call_args
            assert "view" in call_args
            assert "--json" in call_args
            assert "number" in call_args

    def test_get_pr_for_current_branch_with_cwd(self, github_client):
        """Test get_pr_for_current_branch with custom working directory."""
        response = {"number": 100}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            result = github_client.get_pr_for_current_branch(cwd="/custom/path")

            assert result == 100
            # Verify cwd was passed
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get("cwd") == "/custom/path"

    def test_get_pr_for_current_branch_no_pr_exists(self, github_client):
        """Test get_pr_for_current_branch when no PR exists."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="no pull requests found for branch",
            )
            result = github_client.get_pr_for_current_branch()

            # Should return None, not raise
            assert result is None

    def test_get_pr_for_current_branch_null_number(self, github_client):
        """Test get_pr_for_current_branch when number is null in response."""
        response: dict = {"number": None}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            result = github_client.get_pr_for_current_branch()

            assert result is None

    def test_get_pr_for_current_branch_missing_number_key(self, github_client):
        """Test get_pr_for_current_branch when number key is missing."""
        response: dict = {"title": "Some PR"}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            result = github_client.get_pr_for_current_branch()

            assert result is None

    def test_get_pr_for_current_branch_large_pr_number(self, github_client):
        """Test get_pr_for_current_branch with a large PR number."""
        response = {"number": 999999999}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            result = github_client.get_pr_for_current_branch()

            assert result == 999999999

    def test_get_pr_for_current_branch_pr_number_one(self, github_client):
        """Test get_pr_for_current_branch with PR number 1."""
        response = {"number": 1}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            result = github_client.get_pr_for_current_branch()

            assert result == 1


# =============================================================================
# PRStatus Model Additional Tests
# =============================================================================


class TestPRStatusModelExtended:
    """Extended tests for PRStatus model - optional fields and edge cases."""

    def test_pr_status_with_optional_fields(self):
        """Test PRStatus with optional fields set."""
        status = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=2,
            check_details=[],
            resolved_threads=5,
            total_threads=7,
            checks_passed=3,
            checks_failed=0,
            checks_pending=0,
            checks_skipped=1,
            mergeable="MERGEABLE",
            base_branch="develop",
        )
        assert status.resolved_threads == 5
        assert status.total_threads == 7
        assert status.checks_passed == 3
        assert status.checks_skipped == 1
        assert status.mergeable == "MERGEABLE"
        assert status.base_branch == "develop"

    def test_pr_status_default_values(self):
        """Test PRStatus default values for optional fields."""
        status = PRStatus(
            number=1,
            ci_state="PENDING",
            unresolved_threads=0,
            check_details=[],
        )
        assert status.resolved_threads == 0
        assert status.total_threads == 0
        assert status.checks_passed == 0
        assert status.checks_failed == 0
        assert status.checks_pending == 0
        assert status.checks_skipped == 0
        assert status.mergeable == "UNKNOWN"
        assert status.base_branch == "main"

    def test_pr_status_mergeable_states(self):
        """Test PRStatus with various mergeable states."""
        for mergeable in ["MERGEABLE", "CONFLICTING", "UNKNOWN"]:
            status = PRStatus(
                number=1,
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
                mergeable=mergeable,
            )
            assert status.mergeable == mergeable

    def test_pr_status_checks_counters(self):
        """Test PRStatus checks counters."""
        status = PRStatus(
            number=42,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[
                {"name": "test1", "conclusion": "SUCCESS"},
                {"name": "test2", "conclusion": "FAILURE"},
                {"name": "test3", "conclusion": "SKIPPED"},
            ],
            checks_passed=1,
            checks_failed=1,
            checks_pending=0,
            checks_skipped=1,
        )
        assert status.checks_passed == 1
        assert status.checks_failed == 1
        assert status.checks_skipped == 1
        assert len(status.check_details) == 3


# =============================================================================
# Internal Utility Method Tests
# =============================================================================


class TestGitHubClientInternalUtils:
    """Tests for internal utility methods."""

    def test_run_gh_command_with_custom_timeout(self, github_client):
        """Test _run_gh_command with custom timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="success",
                stderr="",
            )
            result = github_client._run_gh_command(
                ["gh", "version"],
                timeout=120,
            )

            assert result.returncode == 0
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["timeout"] == 120

    def test_run_gh_command_default_timeout(self, github_client):
        """Test _run_gh_command uses default timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="success",
                stderr="",
            )
            github_client._run_gh_command(["gh", "version"])

            call_kwargs = mock_run.call_args[1]
            # Default timeout is 30 seconds
            assert call_kwargs["timeout"] == 30

    def test_run_gh_command_captures_output(self, github_client):
        """Test _run_gh_command captures stdout and stderr."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="output text",
                stderr="error text",
            )
            result = github_client._run_gh_command(["gh", "test"])

            assert result.stdout == "output text"
            assert result.stderr == "error text"
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["capture_output"] is True
            assert call_kwargs["text"] is True

    def test_run_gh_command_with_cwd(self, github_client):
        """Test _run_gh_command with custom working directory."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr="",
            )
            github_client._run_gh_command(
                ["gh", "repo", "view"],
                cwd="/path/to/repo",
            )

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["cwd"] == "/path/to/repo"

    def test_run_gh_command_check_false_returns_result(self, github_client):
        """Test _run_gh_command with check=False returns result even on error."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="error",
            )
            result = github_client._run_gh_command(["gh", "fail"], check=False)

            assert result.returncode == 1
            assert result.stderr == "error"

    def test_run_gh_command_check_true_raises_on_error(self, github_client):
        """Test _run_gh_command with check=True raises on non-zero exit."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="command failed",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client._run_gh_command(["gh", "fail"], check=True)

            assert "command failed" in str(exc_info.value)

    def test_run_gh_command_preserves_command_in_error(self, github_client):
        """Test that error includes the command that failed."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="error message",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client._run_gh_command(["gh", "pr", "create"])

            error = exc_info.value
            assert error.command == ["gh", "pr", "create"]
            assert error.exit_code == 1


# =============================================================================
# WorkflowRun to PRStatus Relationship Tests
# =============================================================================


class TestModelRelationships:
    """Tests for relationships between models."""

    def test_workflow_run_can_be_used_with_pr_status(self):
        """Test that WorkflowRun data can inform PRStatus checks."""
        # Simulate getting workflow runs
        runs = [
            WorkflowRun(
                id=1,
                name="Test",
                status="completed",
                conclusion="success",
                url="https://example.com/1",
                head_branch="feature",
                event="pull_request",
            ),
            WorkflowRun(
                id=2,
                name="Lint",
                status="completed",
                conclusion="success",
                url="https://example.com/2",
                head_branch="feature",
                event="pull_request",
            ),
        ]

        # Convert to check details format
        check_details = [
            {
                "name": run.name,
                "status": run.status.upper(),
                "conclusion": run.conclusion.upper() if run.conclusion else None,
                "url": run.url,
            }
            for run in runs
        ]

        # Create PRStatus with these check details
        status = PRStatus(
            number=42,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=check_details,
            checks_passed=2,
        )

        assert len(status.check_details) == 2
        assert status.checks_passed == 2

    def test_models_serialization_round_trip(self):
        """Test that models can be serialized and deserialized."""
        original_run = WorkflowRun(
            id=123,
            name="CI",
            status="completed",
            conclusion="success",
            url="https://example.com",
            head_branch="main",
            event="push",
        )

        # Serialize to dict and back
        data = original_run.model_dump()
        restored_run = WorkflowRun(**data)

        assert restored_run.id == original_run.id
        assert restored_run.name == original_run.name
        assert restored_run.status == original_run.status
        assert restored_run.conclusion == original_run.conclusion

        original_status = PRStatus(
            number=1,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[{"name": "test"}],
        )

        data = original_status.model_dump()
        restored_status = PRStatus(**data)

        assert restored_status.number == original_status.number
        assert restored_status.ci_state == original_status.ci_state
