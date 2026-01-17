"""Tests for the pr CLI command."""

from claude_task_master.cli import app


class TestPRCommand:
    """Tests for the pr command (TODO implementation)."""

    def test_pr_not_implemented(self, cli_runner):
        """Test pr returns failure (not implemented yet)."""
        result = cli_runner.invoke(app, ["pr"])

        # Currently not implemented, should exit with 1
        assert result.exit_code == 1
        assert "PR Status" in result.output
