"""File Checkpointing - Track and restore file changes.

This module provides checkpointing capabilities that allow:
- Tracking file modifications during agent sessions
- Creating restore points for safe rollback
- Reverting to previous file states if needed

Note: Only changes made through Write, Edit, and NotebookEdit tools are tracked.
Changes made through Bash commands are NOT captured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass
class Checkpoint:
    """A checkpoint representing a point in time for file restoration.

    Attributes:
        id: Unique checkpoint identifier (UUID from SDK).
        description: Human-readable description of the checkpoint.
        timestamp: When the checkpoint was created.
        session_id: The session ID this checkpoint belongs to.
        files_modified: List of files modified after this checkpoint.
    """

    id: str
    description: str
    timestamp: datetime = field(default_factory=datetime.now)
    session_id: str | None = None
    files_modified: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "files_modified": self.files_modified,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            description=data["description"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            session_id=data.get("session_id"),
            files_modified=data.get("files_modified", []),
        )


@dataclass
class CheckpointManager:
    """Manages file checkpoints for safe rollback.

    Attributes:
        checkpoints: List of checkpoints in chronological order.
        current_session_id: ID of the current session.
        enable_checkpointing: Whether checkpointing is enabled.
    """

    checkpoints: list[Checkpoint] = field(default_factory=list)
    current_session_id: str | None = None
    enable_checkpointing: bool = True

    def create_checkpoint(
        self,
        checkpoint_id: str,
        description: str,
        session_id: str | None = None,
    ) -> Checkpoint:
        """Create a new checkpoint.

        Args:
            checkpoint_id: Unique checkpoint ID (usually from SDK).
            description: Description of this checkpoint.
            session_id: Optional session ID.

        Returns:
            The created checkpoint.
        """
        checkpoint = Checkpoint(
            id=checkpoint_id,
            description=description,
            session_id=session_id or self.current_session_id,
        )
        self.checkpoints.append(checkpoint)
        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a checkpoint by ID.

        Args:
            checkpoint_id: The checkpoint ID to find.

        Returns:
            The checkpoint if found, None otherwise.
        """
        for checkpoint in self.checkpoints:
            if checkpoint.id == checkpoint_id:
                return checkpoint
        return None

    def get_latest_checkpoint(self) -> Checkpoint | None:
        """Get the most recent checkpoint.

        Returns:
            The latest checkpoint if any exist.
        """
        if not self.checkpoints:
            return None
        return self.checkpoints[-1]

    def list_checkpoints(
        self,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[Checkpoint]:
        """List checkpoints, optionally filtered.

        Args:
            session_id: Filter by session ID if provided.
            limit: Maximum number of checkpoints to return.

        Returns:
            List of checkpoints, most recent first.
        """
        checkpoints = self.checkpoints.copy()

        if session_id:
            checkpoints = [c for c in checkpoints if c.session_id == session_id]

        # Return in reverse chronological order
        checkpoints = list(reversed(checkpoints))

        if limit:
            checkpoints = checkpoints[:limit]

        return checkpoints

    def record_file_modification(self, file_path: str) -> None:
        """Record that a file was modified.

        This should be called when a file is modified to track
        which files changed after each checkpoint.

        Args:
            file_path: Path to the modified file.
        """
        if not self.checkpoints:
            return

        # Add to the latest checkpoint's modified files
        latest = self.checkpoints[-1]
        if file_path not in latest.files_modified:
            latest.files_modified.append(file_path)

    def clear_checkpoints(self) -> None:
        """Clear all checkpoints."""
        self.checkpoints.clear()


def get_checkpointing_env() -> dict[str, str]:
    """Get environment variables needed for SDK file checkpointing.

    Returns:
        Dict of environment variables to enable checkpointing.
    """
    env = dict(os.environ)
    env["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "1"
    return env


@dataclass
class CheckpointingOptions:
    """Options for configuring file checkpointing.

    Attributes:
        enabled: Whether checkpointing is enabled.
        auto_checkpoint_on_task: Create checkpoint before each task.
        keep_count: Number of checkpoints to keep (0 = unlimited).
        checkpoint_dir: Directory for storing checkpoint metadata.
    """

    enabled: bool = False
    auto_checkpoint_on_task: bool = True
    keep_count: int = 10
    checkpoint_dir: Path | None = None

    def to_sdk_options(self) -> dict[str, Any]:
        """Convert to SDK options dict.

        Returns:
            Options dict compatible with ClaudeAgentOptions.
        """
        options: dict[str, Any] = {}

        if self.enabled:
            options["enable_file_checkpointing"] = True
            options["extra_args"] = {"replay-user-messages": None}
            # Environment variables are handled separately via get_checkpointing_env

        return options


class CheckpointError(Exception):
    """Base exception for checkpoint-related errors."""

    pass


class CheckpointNotFoundError(CheckpointError):
    """Raised when a checkpoint cannot be found."""

    def __init__(self, checkpoint_id: str):
        self.checkpoint_id = checkpoint_id
        super().__init__(f"Checkpoint not found: {checkpoint_id}")


class CheckpointRewindError(CheckpointError):
    """Raised when rewinding to a checkpoint fails."""

    def __init__(self, checkpoint_id: str, reason: str):
        self.checkpoint_id = checkpoint_id
        self.reason = reason
        super().__init__(f"Failed to rewind to checkpoint {checkpoint_id}: {reason}")
