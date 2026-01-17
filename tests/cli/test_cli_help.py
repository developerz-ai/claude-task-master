"""Tests for CLI help text."""

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app

from .conftest import strip_ansi

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    return CliRunner()


# =============================================================================
# Help Text Tests
# =============================================================================


class TestCLIHelpText:
    """Tests for CLI help text."""

    def test_start_help(self, cli_runner):
        """Test start command help."""
        result = cli_runner.invoke(app, ["start", "--help"])
        output = strip_ansi(result.output)

        assert "goal" in output.lower()
        assert "--model" in output
        assert "--auto-merge" in output
        assert "--max-sessions" in output
        assert "--pause-on-pr" in output

    def test_status_help(self, cli_runner):
        """Test status command help."""
        result = cli_runner.invoke(app, ["status", "--help"])

        assert "status" in result.output.lower()

    def test_plan_help(self, cli_runner):
        """Test plan command help."""
        result = cli_runner.invoke(app, ["plan", "--help"])

        assert "plan" in result.output.lower()

    def test_logs_help(self, cli_runner):
        """Test logs command help."""
        result = cli_runner.invoke(app, ["logs", "--help"])
        output = strip_ansi(result.output)

        assert "--tail" in output
        assert "--session" in output

    def test_context_help(self, cli_runner):
        """Test context command help."""
        result = cli_runner.invoke(app, ["context", "--help"])

        assert "context" in result.output.lower()

    def test_progress_help(self, cli_runner):
        """Test progress command help."""
        result = cli_runner.invoke(app, ["progress", "--help"])

        assert "progress" in result.output.lower()

    def test_comments_help(self, cli_runner):
        """Test comments command help."""
        result = cli_runner.invoke(app, ["comments", "--help"])
        output = strip_ansi(result.output)

        assert "--pr" in output

    def test_pr_help(self, cli_runner):
        """Test pr command help."""
        result = cli_runner.invoke(app, ["pr", "--help"])

        assert "pr" in result.output.lower()

    def test_clean_help(self, cli_runner):
        """Test clean command help."""
        result = cli_runner.invoke(app, ["clean", "--help"])
        output = strip_ansi(result.output)

        assert "--force" in output

    def test_doctor_help(self, cli_runner):
        """Test doctor command help."""
        result = cli_runner.invoke(app, ["doctor", "--help"])

        assert "doctor" in result.output.lower()

    def test_resume_help(self, cli_runner):
        """Test resume command help."""
        result = cli_runner.invoke(app, ["resume", "--help"])

        assert "resume" in result.output.lower()
