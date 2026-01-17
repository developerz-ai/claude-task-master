"""Tests for CLI app configuration."""

from claude_task_master.cli import app


class TestCLIAppConfiguration:
    """Tests for CLI app configuration."""

    def test_app_name(self):
        """Test app has correct name."""
        assert app.info.name == "claude-task-master"

    def test_app_help_text(self):
        """Test app has help text."""
        assert app.info.help and "Claude Agent SDK" in app.info.help

    def test_app_commands_registered(self, cli_runner):
        """Test all commands are registered."""
        result = cli_runner.invoke(app, ["--help"])

        assert "start" in result.output
        assert "resume" in result.output
        assert "status" in result.output
        assert "plan" in result.output
        assert "logs" in result.output
        assert "context" in result.output
        assert "progress" in result.output
        assert "comments" in result.output
        assert "pr" in result.output
        assert "clean" in result.output
        assert "doctor" in result.output
