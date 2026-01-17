"""PR Context Management for State Manager.

This module provides methods for managing PR-related context data,
including comments, CI failures, and context loading/clearing.

These methods are mixed into the StateManager class via the PRContextMixin.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class PRContextMixin:
    """Mixin providing PR context management methods for StateManager.

    This mixin adds methods to handle PR comments, CI failures, and related
    context for debugging and review purposes.

    Requires:
        - self.state_dir: Path to the state directory
    """

    # This will be set by StateManager
    state_dir: Path

    def get_pr_dir(self, pr_number: int) -> Path:
        """Get the directory for a specific PR's context.

        Structure: .claude-task-master/debugging/pr/{number}/

        Args:
            pr_number: The PR number.

        Returns:
            Path to the PR directory (created if it doesn't exist).
        """
        pr_dir = self.state_dir / "debugging" / "pr" / str(pr_number)
        pr_dir.mkdir(parents=True, exist_ok=True)
        return pr_dir

    def save_pr_comments(self, pr_number: int, comments: list[dict]) -> None:
        """Save PR comments to files for Claude to read.

        Each comment is saved to a separate file for easy reading.

        Args:
            pr_number: The PR number.
            comments: List of comment dicts with author, path, line, body.
        """
        pr_dir = self.get_pr_dir(pr_number)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(exist_ok=True)

        # Clear old comments
        for old_file in comments_dir.glob("*.txt"):
            old_file.unlink()

        # Save each comment to a separate file
        for i, comment in enumerate(comments, 1):
            thread_id = comment.get("thread_id", "")
            comment_id = comment.get("comment_id", "")
            author = comment.get("author", "unknown")
            path = comment.get("path", "general")
            line = comment.get("line", "N/A")
            body = comment.get("body", "")
            is_resolved = comment.get("is_resolved", False)

            # Create filename from sanitized path
            safe_path = path.replace("/", "_").replace("\\", "_") if path else "general"
            # Sanitize line number (could be "N/A" or None)
            safe_line = str(line).replace("/", "_").replace("\\", "_") if line else "0"
            filename = f"{i:03d}_{safe_path}_L{safe_line}.txt"

            content = f"""Thread ID: {thread_id}
Comment ID: {comment_id}
File: {path}
Line: {line}
Author: {author}
Status: {"Resolved" if is_resolved else "Unresolved"}

{body}
"""
            (comments_dir / filename).write_text(content)

        # Also save a summary file
        summary_file = pr_dir / "comments_summary.txt"
        summary_lines = [
            f"PR #{pr_number} Review Comments",
            f"Total: {len(comments)} comments",
            "",
            "Files with comments:",
        ]
        paths = {c.get("path", "general") for c in comments}
        for p in sorted(paths):
            summary_lines.append(f"  - {p}")

        summary_file.write_text("\n".join(summary_lines))

    def save_ci_failure(self, pr_number: int, check_name: str, logs: str) -> None:
        """Save CI failure logs for Claude to read.

        Args:
            pr_number: The PR number.
            check_name: Name of the failing check.
            logs: The failure logs.
        """
        pr_dir = self.get_pr_dir(pr_number)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(exist_ok=True)

        # Sanitize check name for filename
        safe_name = check_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        filename = f"failed_{safe_name}.txt"

        content = f"""CI Check Failed: {check_name}
PR: #{pr_number}

{"=" * 60}
FAILURE LOGS:
{"=" * 60}

{logs}
"""
        (ci_dir / filename).write_text(content)

    def load_pr_context(self, pr_number: int) -> str:
        """Load all PR context (comments + CI failures) as a single string.

        This gives Claude all the context it needs to address issues.

        Args:
            pr_number: The PR number.

        Returns:
            Combined context string.
        """
        pr_dir = self.get_pr_dir(pr_number)
        if not pr_dir.exists():
            return ""

        sections = []

        # Load comments
        comments_dir = pr_dir / "comments"
        if comments_dir.exists():
            comment_files = sorted(comments_dir.glob("*.txt"))
            if comment_files:
                sections.append("## Review Comments\n")
                for cf in comment_files:
                    sections.append(f"### {cf.stem}\n{cf.read_text()}\n")

        # Load CI failures
        ci_dir = pr_dir / "ci"
        if ci_dir.exists():
            ci_files = sorted(ci_dir.glob("failed_*.txt"))
            if ci_files:
                sections.append("## CI Failures\n")
                for cf in ci_files:
                    sections.append(cf.read_text())

        return "\n".join(sections)

    def clear_pr_context(self, pr_number: int) -> None:
        """Clear PR context after PR is merged.

        Args:
            pr_number: The PR number.
        """
        # Use the same path structure as get_pr_dir
        pr_dir = self.state_dir / "debugging" / "pr" / str(pr_number)
        if pr_dir.exists():
            shutil.rmtree(pr_dir)
