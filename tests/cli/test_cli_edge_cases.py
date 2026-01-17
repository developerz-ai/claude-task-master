"""Edge case tests for CLI commands."""

import json
from datetime import datetime
from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestCLIEdgeCases:
    """Edge case tests for CLI commands."""

    def test_status_with_no_current_pr(self, cli_runner, temp_dir, mock_state_dir, mock_goal_file):
        """Test status when current_pr is None."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "working",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,  # No PR
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,  # Unlimited
                "pause_on_pr": False,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "unlimited" in result.output  # max_sessions is None

    def test_logs_with_empty_log_file(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_logs_dir
    ):
        """Test logs with empty log file."""
        log_file = mock_logs_dir / "run-20250115-120000.txt"
        log_file.write_text("")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 0

    def test_logs_with_tail_larger_than_file(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_logs_dir
    ):
        """Test logs with tail option larger than file content."""
        log_file = mock_logs_dir / "run-20250115-120000.txt"
        log_file.write_text("Line 1\nLine 2\nLine 3\n")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs", "--tail", "100"])

        assert result.exit_code == 0
        assert "Line 1" in result.output
        assert "Line 2" in result.output
        assert "Line 3" in result.output

    def test_context_with_empty_context(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test context with empty context file."""
        context_file = mock_state_dir / "context.md"
        context_file.write_text("")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["context"])

        # Empty context should show "No context accumulated"
        assert result.exit_code == 0

    def test_progress_with_empty_progress(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test progress with empty progress file."""
        progress_file = mock_state_dir / "progress.md"
        progress_file.write_text("")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["progress"])

        # Empty progress should show "No progress recorded"
        assert result.exit_code == 0

    def test_plan_with_complex_markdown(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test plan with complex markdown content."""
        plan_file = mock_state_dir / "plan.md"
        plan_file.write_text("""# Complex Plan

## Phase 1

```python
def example():
    return "Hello"
```

| Table | Header |
|-------|--------|
| Cell  | Data   |

> Blockquote with **bold** and *italic*
""")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["plan"])

        assert result.exit_code == 0
        assert "Complex Plan" in result.output
