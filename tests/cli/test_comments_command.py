"""Tests for the comments CLI command."""

from claude_task_master.cli import app


class TestCommentsCommand:
    """Tests for the comments command (TODO implementation)."""

    def test_comments_not_implemented(self, cli_runner):
        """Test comments returns failure (not implemented yet)."""
        result = cli_runner.invoke(app, ["comments"])

        # Currently not implemented, should exit with 1
        assert result.exit_code == 1
        assert "PR Comments" in result.output

    def test_comments_with_pr_option(self, cli_runner):
        """Test comments with --pr option."""
        result = cli_runner.invoke(app, ["comments", "--pr", "123"])

        # Currently not implemented
        assert result.exit_code == 1
