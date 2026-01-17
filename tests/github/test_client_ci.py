"""Tests for GitHub client CI checks and workflow run functionality."""

import json
from unittest.mock import MagicMock, patch

from claude_task_master.github.client import PRStatus
from claude_task_master.github.client_ci import WorkflowRun

# =============================================================================
# GitHubClient.get_workflow_runs Tests
# =============================================================================


class TestGitHubClientGetWorkflowRuns:
    """Tests for workflow runs retrieval."""

    def test_get_workflow_runs_success(self, github_client):
        """Test successful workflow runs retrieval."""
        response = [
            {
                "databaseId": 123,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/123",
                "headBranch": "main",
                "event": "push",
            },
            {
                "databaseId": 124,
                "name": "CD",
                "status": "in_progress",
                "conclusion": None,
                "url": "https://github.com/owner/repo/actions/runs/124",
                "headBranch": "feature",
                "event": "pull_request",
            },
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            runs = github_client.get_workflow_runs(limit=5)

            assert len(runs) == 2
            assert runs[0].id == 123
            assert runs[0].name == "CI"
            assert runs[0].status == "completed"
            assert runs[0].conclusion == "success"
            assert runs[1].status == "in_progress"
            assert runs[1].conclusion is None

    def test_get_workflow_runs_with_branch_filter(self, github_client):
        """Test workflow runs with branch filter."""
        response = [
            {
                "databaseId": 125,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/125",
                "headBranch": "feature-branch",
                "event": "push",
            }
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            runs = github_client.get_workflow_runs(limit=5, branch="feature-branch")

            call_args = mock_run.call_args[0][0]
            assert "--branch" in call_args
            assert "feature-branch" in call_args
            assert len(runs) == 1

    def test_get_workflow_runs_empty_list(self, github_client):
        """Test when no workflow runs exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
                stderr="",
            )
            runs = github_client.get_workflow_runs()
            assert runs == []

    def test_get_workflow_runs_limit_parameter(self, github_client):
        """Test that limit parameter is passed correctly."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
                stderr="",
            )
            github_client.get_workflow_runs(limit=10)

            call_args = mock_run.call_args[0][0]
            assert "--limit" in call_args
            assert "10" in call_args

    def test_get_workflow_runs_various_events(self, github_client):
        """Test workflow runs with various event types."""
        response = [
            {
                "databaseId": 126,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/126",
                "headBranch": "main",
                "event": "push",
            },
            {
                "databaseId": 127,
                "name": "PR Check",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/127",
                "headBranch": "feature",
                "event": "pull_request",
            },
            {
                "databaseId": 128,
                "name": "Release",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/128",
                "headBranch": "main",
                "event": "release",
            },
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            runs = github_client.get_workflow_runs(limit=10)

            assert len(runs) == 3
            assert runs[0].event == "push"
            assert runs[1].event == "pull_request"
            assert runs[2].event == "release"

    def test_get_workflow_runs_various_conclusions(self, github_client):
        """Test workflow runs with various conclusion types."""
        response = [
            {
                "databaseId": 129,
                "name": "Test",
                "status": "completed",
                "conclusion": "success",
                "url": "https://example.com/129",
                "headBranch": "main",
                "event": "push",
            },
            {
                "databaseId": 130,
                "name": "Test",
                "status": "completed",
                "conclusion": "failure",
                "url": "https://example.com/130",
                "headBranch": "main",
                "event": "push",
            },
            {
                "databaseId": 131,
                "name": "Test",
                "status": "completed",
                "conclusion": "cancelled",
                "url": "https://example.com/131",
                "headBranch": "main",
                "event": "push",
            },
            {
                "databaseId": 132,
                "name": "Test",
                "status": "completed",
                "conclusion": "skipped",
                "url": "https://example.com/132",
                "headBranch": "main",
                "event": "push",
            },
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            runs = github_client.get_workflow_runs(limit=10)

            conclusions = [run.conclusion for run in runs]
            assert "success" in conclusions
            assert "failure" in conclusions
            assert "cancelled" in conclusions
            assert "skipped" in conclusions


# =============================================================================
# GitHubClient.get_workflow_run_status Tests
# =============================================================================


class TestGitHubClientGetWorkflowRunStatus:
    """Tests for workflow run status retrieval."""

    def test_get_workflow_run_status_with_run_id(self, github_client):
        """Test getting status for a specific run."""
        response = {
            "status": "completed",
            "conclusion": "success",
            "jobs": [
                {"name": "build", "status": "completed", "conclusion": "success"},
                {"name": "test", "status": "completed", "conclusion": "success"},
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            status = github_client.get_workflow_run_status(run_id=123)

            assert "Run #123" in status
            assert "completed" in status
            assert "success" in status
            assert "build" in status
            assert "test" in status

    def test_get_workflow_run_status_without_run_id(self, github_client):
        """Test getting status for latest run."""
        runs_response = [
            {
                "databaseId": 999,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/999",
                "headBranch": "main",
                "event": "push",
            }
        ]
        status_response = {
            "status": "completed",
            "conclusion": "success",
            "jobs": [],
        }
        with patch("subprocess.run") as mock_run:
            # First call for get_workflow_runs
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(runs_response),
                stderr="",
            )

            # Then call again for status - mock returns runs first, then status
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "list" in cmd:
                    return MagicMock(returncode=0, stdout=json.dumps(runs_response))
                else:
                    return MagicMock(returncode=0, stdout=json.dumps(status_response))

            mock_run.side_effect = side_effect

            status = github_client.get_workflow_run_status()
            assert "Run #999" in status

    def test_get_workflow_run_status_no_runs_found(self, github_client):
        """Test status when no runs exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
                stderr="",
            )
            status = github_client.get_workflow_run_status()
            assert "No workflow runs found" in status

    def test_get_workflow_run_status_with_failed_jobs(self, github_client):
        """Test status output for failed jobs."""
        response = {
            "status": "completed",
            "conclusion": "failure",
            "jobs": [
                {"name": "build", "status": "completed", "conclusion": "success"},
                {"name": "test", "status": "completed", "conclusion": "failure"},
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            status = github_client.get_workflow_run_status(run_id=456)

            assert "checkmark" in status or "success" in status.lower() or "build" in status
            assert "failure" in status.lower() or "test" in status

    def test_get_workflow_run_status_in_progress(self, github_client):
        """Test status for in-progress run."""
        response = {
            "status": "in_progress",
            "conclusion": None,
            "jobs": [
                {"name": "build", "status": "in_progress", "conclusion": None},
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            status = github_client.get_workflow_run_status(run_id=789)

            assert "in_progress" in status or "in progress" in status.lower()

    def test_get_workflow_run_status_multiple_jobs(self, github_client):
        """Test status with multiple jobs in various states."""
        response = {
            "status": "in_progress",
            "conclusion": None,
            "jobs": [
                {"name": "lint", "status": "completed", "conclusion": "success"},
                {"name": "build", "status": "completed", "conclusion": "success"},
                {"name": "unit-tests", "status": "in_progress", "conclusion": None},
                {"name": "integration-tests", "status": "queued", "conclusion": None},
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            status = github_client.get_workflow_run_status(run_id=100)

            # Should contain all job names
            assert "lint" in status
            assert "build" in status
            assert "unit-tests" in status
            assert "integration-tests" in status

    def test_get_workflow_run_status_empty_jobs(self, github_client):
        """Test status with no jobs."""
        response = {
            "status": "completed",
            "conclusion": "success",
            "jobs": [],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            status = github_client.get_workflow_run_status(run_id=200)

            assert "Run #200" in status
            assert "completed" in status


# =============================================================================
# GitHubClient.get_failed_run_logs Tests
# =============================================================================


class TestGitHubClientGetFailedRunLogs:
    """Tests for failed run logs retrieval."""

    def test_get_failed_run_logs_with_run_id(self, github_client):
        """Test getting logs for a specific failed run."""
        log_output = """test-job\tError: Test failed
test-job\tAssertionError: expected True
test-job\t  at test_file.py:42"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=log_output,
                stderr="",
            )
            logs = github_client.get_failed_run_logs(run_id=123)

            assert "Error: Test failed" in logs
            assert "AssertionError" in logs

    def test_get_failed_run_logs_without_run_id(self, github_client):
        """Test getting logs for latest failed run."""
        log_output = "build\tCompilation failed"
        workflow_runs_response = json.dumps(
            [
                {
                    "databaseId": 123,
                    "name": "CI",
                    "status": "completed",
                    "conclusion": "failure",
                    "url": "https://example.com",
                    "headBranch": "main",
                    "event": "push",
                }
            ]
        )
        with patch("subprocess.run") as mock_run:
            # First call returns workflow runs, second returns logs
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=workflow_runs_response, stderr=""),
                MagicMock(returncode=0, stdout=log_output, stderr=""),
            ]
            result = github_client.get_failed_run_logs()

            # Check that second call (log fetch) has correct args
            call_args = mock_run.call_args_list[1][0][0]
            assert "gh" in call_args
            assert "run" in call_args
            assert "view" in call_args
            assert "123" in call_args  # Run ID
            assert "--log-failed" in call_args
            assert result == log_output

    def test_get_failed_run_logs_truncates_long_output(self, github_client):
        """Test that long logs are truncated."""
        # Create output with more than 100 lines
        log_lines = [f"Line {i}: Some error message" for i in range(200)]
        log_output = "\n".join(log_lines)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=log_output,
                stderr="",
            )
            logs = github_client.get_failed_run_logs(run_id=123, max_lines=100)

            # Should be truncated
            assert "more lines" in logs
            # Should only show first 100 lines
            assert "Line 0:" in logs
            assert "Line 99:" in logs or "Line 100:" not in logs.split("...")[0]

    def test_get_failed_run_logs_error(self, github_client):
        """Test handling of errors when getting logs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Run not found",
            )
            logs = github_client.get_failed_run_logs(run_id=999)

            assert "Error getting logs" in logs

    def test_get_failed_run_logs_short_output(self, github_client):
        """Test that short logs are not truncated."""
        log_output = "Line 1\nLine 2\nLine 3"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=log_output,
                stderr="",
            )
            logs = github_client.get_failed_run_logs(run_id=123, max_lines=100)

            assert logs == "Line 1\nLine 2\nLine 3"
            assert "more lines" not in logs

    def test_get_failed_run_logs_exact_limit(self, github_client):
        """Test logs at exactly the limit."""
        log_lines = [f"Line {i}" for i in range(100)]
        log_output = "\n".join(log_lines)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=log_output,
                stderr="",
            )
            logs = github_client.get_failed_run_logs(run_id=123, max_lines=100)

            # Should not be truncated at exactly the limit
            assert "more lines" not in logs

    def test_get_failed_run_logs_various_error_formats(self, github_client):
        """Test logs with various error message formats."""
        log_output = """build\tERROR: npm ERR! code ELIFECYCLE
build\tERROR: npm ERR! errno 1
test\tFAILED tests/test_main.py::test_function - AssertionError
test\tTraceback (most recent call last):
test\t  File "test_main.py", line 42, in test_function
test\t    assert result == expected"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=log_output,
                stderr="",
            )
            logs = github_client.get_failed_run_logs(run_id=123)

            assert "ERROR" in logs
            assert "FAILED" in logs
            assert "Traceback" in logs


# =============================================================================
# GitHubClient.wait_for_ci Tests
# =============================================================================


class TestGitHubClientWaitForCI:
    """Tests for CI waiting functionality."""

    def test_wait_for_ci_success_with_pr(self, github_client):
        """Test waiting for CI with PR number - success case."""
        success_status = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )
        with patch.object(github_client, "get_pr_status", return_value=success_status):
            success, message = github_client.wait_for_ci(pr_number=123, timeout=60)

            assert success is True
            assert "passed" in message

    def test_wait_for_ci_failure_with_pr(self, github_client):
        """Test waiting for CI with PR number - failure case."""
        failure_status = PRStatus(
            number=123,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[],
        )
        with patch.object(github_client, "get_pr_status", return_value=failure_status):
            success, message = github_client.wait_for_ci(pr_number=123, timeout=60)

            assert success is False
            assert "failed" in message.lower() or "FAILURE" in message

    def test_wait_for_ci_error_state(self, github_client):
        """Test waiting for CI with ERROR state."""
        error_status = PRStatus(
            number=123,
            ci_state="ERROR",
            unresolved_threads=0,
            check_details=[],
        )
        with patch.object(github_client, "get_pr_status", return_value=error_status):
            success, message = github_client.wait_for_ci(pr_number=123, timeout=60)

            assert success is False
            assert "ERROR" in message

    def test_wait_for_ci_timeout(self, github_client):
        """Test waiting for CI times out."""
        pending_status = PRStatus(
            number=123,
            ci_state="PENDING",
            unresolved_threads=0,
            check_details=[],
        )
        with patch.object(github_client, "get_pr_status", return_value=pending_status):
            with patch("time.sleep"):  # Don't actually sleep
                with patch("time.time") as mock_time:
                    # Simulate timeout
                    mock_time.side_effect = [0, 0, 100, 200, 300, 400]
                    success, message = github_client.wait_for_ci(pr_number=123, timeout=1)

                    assert success is False
                    assert "Timeout" in message

    def test_wait_for_ci_workflow_success(self, github_client):
        """Test waiting for CI without PR - workflow success."""
        success_run = WorkflowRun(
            id=456,
            name="CI",
            status="completed",
            conclusion="success",
            url="https://github.com/owner/repo/actions/runs/456",
            head_branch="main",
            event="push",
        )
        with patch.object(github_client, "get_workflow_runs", return_value=[success_run]):
            success, message = github_client.wait_for_ci(timeout=60)

            assert success is True
            assert "succeeded" in message

    def test_wait_for_ci_workflow_failure(self, github_client):
        """Test waiting for CI without PR - workflow failure."""
        failed_run = WorkflowRun(
            id=456,
            name="CI",
            status="completed",
            conclusion="failure",
            url="https://github.com/owner/repo/actions/runs/456",
            head_branch="main",
            event="push",
        )
        with patch.object(github_client, "get_workflow_runs", return_value=[failed_run]):
            success, message = github_client.wait_for_ci(timeout=60)

            assert success is False
            assert "failed" in message.lower()

    def test_wait_for_ci_workflow_cancelled(self, github_client):
        """Test waiting for CI without PR - workflow cancelled."""
        cancelled_run = WorkflowRun(
            id=456,
            name="CI",
            status="completed",
            conclusion="cancelled",
            url="https://github.com/owner/repo/actions/runs/456",
            head_branch="main",
            event="push",
        )
        with patch.object(github_client, "get_workflow_runs", return_value=[cancelled_run]):
            success, message = github_client.wait_for_ci(timeout=60)

            assert success is False
            # Cancelled should be treated as failure
            assert "cancelled" in message.lower() or "failed" in message.lower()

    def test_wait_for_ci_pending_then_success(self, github_client):
        """Test waiting for CI that goes from pending to success."""
        pending_status = PRStatus(
            number=123,
            ci_state="PENDING",
            unresolved_threads=0,
            check_details=[],
        )
        success_status = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )
        call_count = [0]

        def mock_get_status(pr_num):
            call_count[0] += 1
            if call_count[0] < 3:
                return pending_status
            return success_status

        with patch.object(github_client, "get_pr_status", side_effect=mock_get_status):
            with patch("time.sleep"):  # Don't actually sleep
                with patch("time.time") as mock_time:
                    # Simulate time passing but not timing out
                    mock_time.side_effect = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
                    success, message = github_client.wait_for_ci(pr_number=123, timeout=120)

                    assert success is True
                    assert "passed" in message

    def test_wait_for_ci_with_check_details(self, github_client):
        """Test waiting for CI with check details in response."""
        status_with_details = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[
                {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ],
        )
        with patch.object(github_client, "get_pr_status", return_value=status_with_details):
            success, message = github_client.wait_for_ci(pr_number=123, timeout=60)

            assert success is True

    def test_wait_for_ci_no_workflow_runs(self, github_client):
        """Test waiting for CI when no workflow runs exist."""
        with patch.object(github_client, "get_workflow_runs", return_value=[]):
            with patch("time.sleep"):
                with patch("time.time") as mock_time:
                    mock_time.side_effect = [0, 0, 100, 200, 300, 400]
                    success, message = github_client.wait_for_ci(timeout=1)

                    assert success is False
                    # Should timeout waiting for runs


# =============================================================================
# WorkflowRun Model Tests
# =============================================================================


class TestWorkflowRunModel:
    """Tests for the WorkflowRun model."""

    def test_workflow_run_creation(self):
        """Test creating a WorkflowRun with all fields."""
        run = WorkflowRun(
            id=123,
            name="CI Pipeline",
            status="completed",
            conclusion="success",
            url="https://github.com/owner/repo/actions/runs/123",
            head_branch="main",
            event="push",
        )
        assert run.id == 123
        assert run.name == "CI Pipeline"
        assert run.status == "completed"
        assert run.conclusion == "success"
        assert run.url == "https://github.com/owner/repo/actions/runs/123"
        assert run.head_branch == "main"
        assert run.event == "push"

    def test_workflow_run_with_none_conclusion(self):
        """Test creating a WorkflowRun with None conclusion (in progress)."""
        run = WorkflowRun(
            id=456,
            name="Build",
            status="in_progress",
            conclusion=None,
            url="https://github.com/owner/repo/actions/runs/456",
            head_branch="feature",
            event="pull_request",
        )
        assert run.id == 456
        assert run.status == "in_progress"
        assert run.conclusion is None

    def test_workflow_run_model_dump(self):
        """Test that WorkflowRun can be serialized to dict."""
        run = WorkflowRun(
            id=789,
            name="Test",
            status="completed",
            conclusion="failure",
            url="https://example.com/789",
            head_branch="develop",
            event="schedule",
        )
        data = run.model_dump()
        assert data["id"] == 789
        assert data["name"] == "Test"
        assert data["status"] == "completed"
        assert data["conclusion"] == "failure"
        assert data["head_branch"] == "develop"
        assert data["event"] == "schedule"

    def test_workflow_run_various_statuses(self):
        """Test WorkflowRun with various status values."""
        statuses = ["queued", "in_progress", "completed", "waiting"]
        for status in statuses:
            run = WorkflowRun(
                id=1,
                name="Test",
                status=status,
                conclusion=None if status != "completed" else "success",
                url="https://example.com/1",
                head_branch="main",
                event="push",
            )
            assert run.status == status
