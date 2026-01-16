"""Tests for StateManager PR context methods."""

import shutil
from collections.abc import Generator
from pathlib import Path

import pytest

from claude_task_master.core.state import StateManager


@pytest.fixture
def state_manager(tmp_path: Path) -> Generator[StateManager, None, None]:
    """Create a StateManager with a temporary directory."""
    # Use explicit state_dir to avoid relative path issues
    state_dir = tmp_path / ".claude-task-master"
    sm = StateManager(state_dir=state_dir)
    yield sm
    # Cleanup temp directory
    if state_dir.exists():
        shutil.rmtree(state_dir)


class TestPRContextMethods:
    """Tests for PR context storage and retrieval."""

    def test_get_pr_dir_creates_directory(self, state_manager: StateManager) -> None:
        """Test that get_pr_dir creates the PR directory."""
        pr_dir = state_manager.get_pr_dir(123)
        assert pr_dir.exists()
        assert pr_dir.name == "123"
        assert pr_dir.parent.name == "prs"

    def test_get_pr_dir_returns_same_path(self, state_manager: StateManager) -> None:
        """Test that get_pr_dir returns consistent paths."""
        pr_dir1 = state_manager.get_pr_dir(123)
        pr_dir2 = state_manager.get_pr_dir(123)
        assert pr_dir1 == pr_dir2

    def test_save_pr_comments_creates_files(self, state_manager: StateManager) -> None:
        """Test that save_pr_comments creates comment files."""
        comments = [
            {
                "author": "reviewer1",
                "path": "src/main.py",
                "line": 42,
                "body": "Please fix this.",
                "is_resolved": False,
            },
            {
                "author": "reviewer2",
                "path": "src/utils.py",
                "line": 10,
                "body": "Good job!",
                "is_resolved": True,
            },
        ]
        state_manager.save_pr_comments(123, comments)

        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        assert comments_dir.exists()

        comment_files = list(comments_dir.glob("*.txt"))
        assert len(comment_files) == 2

    def test_save_pr_comments_creates_summary(self, state_manager: StateManager) -> None:
        """Test that save_pr_comments creates a summary file."""
        comments = [
            {
                "author": "reviewer1",
                "path": "src/main.py",
                "line": 42,
                "body": "Please fix this.",
            },
        ]
        state_manager.save_pr_comments(123, comments)

        pr_dir = state_manager.get_pr_dir(123)
        summary_file = pr_dir / "comments_summary.txt"
        assert summary_file.exists()
        content = summary_file.read_text()
        assert "PR #123" in content
        assert "Total: 1 comments" in content

    def test_save_pr_comments_handles_missing_fields(self, state_manager: StateManager) -> None:
        """Test that save_pr_comments handles missing optional fields."""
        comments = [
            {
                "body": "General comment",
            },
        ]
        state_manager.save_pr_comments(123, comments)

        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comment_files = list(comments_dir.glob("*.txt"))
        assert len(comment_files) == 1

        content = comment_files[0].read_text()
        assert "General comment" in content
        assert "Author: unknown" in content

    def test_save_pr_comments_clears_old_comments(self, state_manager: StateManager) -> None:
        """Test that save_pr_comments clears old comments."""
        # Save first set of comments
        state_manager.save_pr_comments(123, [{"body": "Old comment"}])

        # Save new comments
        state_manager.save_pr_comments(123, [{"body": "New comment"}])

        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comment_files = list(comments_dir.glob("*.txt"))
        assert len(comment_files) == 1

        content = comment_files[0].read_text()
        assert "New comment" in content
        assert "Old comment" not in content

    def test_save_ci_failure_creates_file(self, state_manager: StateManager) -> None:
        """Test that save_ci_failure creates failure log file."""
        state_manager.save_ci_failure(123, "tests", "Error: Test failed\nAssertionError")

        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        assert ci_dir.exists()

        ci_files = list(ci_dir.glob("failed_*.txt"))
        assert len(ci_files) == 1
        assert "tests" in ci_files[0].name

        content = ci_files[0].read_text()
        assert "CI Check Failed: tests" in content
        assert "Error: Test failed" in content

    def test_save_ci_failure_sanitizes_check_name(self, state_manager: StateManager) -> None:
        """Test that save_ci_failure sanitizes check names for filenames."""
        state_manager.save_ci_failure(123, "build/test runner", "Failed")

        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_files = list(ci_dir.glob("failed_*.txt"))
        assert len(ci_files) == 1
        # Check that / and spaces are replaced
        assert "/" not in ci_files[0].name
        assert " " not in ci_files[0].name

    def test_load_pr_context_empty_when_no_context(self, state_manager: StateManager) -> None:
        """Test that load_pr_context returns empty string when no context."""
        context = state_manager.load_pr_context(999)
        assert context == ""

    def test_load_pr_context_loads_comments(self, state_manager: StateManager) -> None:
        """Test that load_pr_context loads saved comments."""
        comments = [{"author": "reviewer", "body": "Please fix this."}]
        state_manager.save_pr_comments(123, comments)

        context = state_manager.load_pr_context(123)
        assert "Review Comments" in context
        assert "Please fix this." in context

    def test_load_pr_context_loads_ci_failures(self, state_manager: StateManager) -> None:
        """Test that load_pr_context loads saved CI failures."""
        state_manager.save_ci_failure(123, "tests", "Test failed")

        context = state_manager.load_pr_context(123)
        assert "CI Failures" in context
        assert "Test failed" in context

    def test_load_pr_context_loads_both(self, state_manager: StateManager) -> None:
        """Test that load_pr_context loads both comments and CI failures."""
        state_manager.save_pr_comments(123, [{"body": "Comment text"}])
        state_manager.save_ci_failure(123, "tests", "CI failure text")

        context = state_manager.load_pr_context(123)
        assert "Review Comments" in context
        assert "Comment text" in context
        assert "CI Failures" in context
        assert "CI failure text" in context

    def test_clear_pr_context_removes_directory(self, state_manager: StateManager) -> None:
        """Test that clear_pr_context removes the PR directory."""
        state_manager.save_pr_comments(123, [{"body": "Comment"}])
        state_manager.save_ci_failure(123, "tests", "Failure")

        pr_dir = state_manager.state_dir / "prs" / "123"
        assert pr_dir.exists()

        state_manager.clear_pr_context(123)
        assert not pr_dir.exists()

    def test_clear_pr_context_handles_nonexistent(self, state_manager: StateManager) -> None:
        """Test that clear_pr_context handles nonexistent PR."""
        # Should not raise
        state_manager.clear_pr_context(999)

    def test_save_pr_comments_handles_path_sanitization(self, state_manager: StateManager) -> None:
        """Test that save_pr_comments sanitizes file paths."""
        comments = [
            {
                "author": "reviewer",
                "path": "src/components/Button.tsx",
                "line": 10,
                "body": "Fix this",
            },
        ]
        state_manager.save_pr_comments(123, comments)

        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comment_files = list(comments_dir.glob("*.txt"))
        assert len(comment_files) == 1
        # Check that / is replaced in filename
        assert "/" not in comment_files[0].name
