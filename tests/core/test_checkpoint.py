"""Tests for the checkpoint module."""

from datetime import datetime

from claude_task_master.core.checkpoint import (
    Checkpoint,
    CheckpointError,
    CheckpointingOptions,
    CheckpointManager,
    CheckpointNotFoundError,
    CheckpointRewindError,
    get_checkpointing_env,
)

# =============================================================================
# Checkpoint Tests
# =============================================================================


class TestCheckpoint:
    """Tests for Checkpoint dataclass."""

    def test_create_checkpoint(self) -> None:
        """Test creating a checkpoint."""
        checkpoint = Checkpoint(
            id="uuid-123",
            description="Before refactoring",
        )
        assert checkpoint.id == "uuid-123"
        assert checkpoint.description == "Before refactoring"
        assert checkpoint.session_id is None
        assert checkpoint.files_modified == []

    def test_checkpoint_with_session(self) -> None:
        """Test checkpoint with session ID."""
        checkpoint = Checkpoint(
            id="uuid-456",
            description="Task start",
            session_id="session-789",
        )
        assert checkpoint.session_id == "session-789"

    def test_checkpoint_with_files(self) -> None:
        """Test checkpoint with modified files."""
        checkpoint = Checkpoint(
            id="uuid-789",
            description="After edits",
            files_modified=["/src/main.py", "/src/utils.py"],
        )
        assert len(checkpoint.files_modified) == 2
        assert "/src/main.py" in checkpoint.files_modified

    def test_to_dict(self) -> None:
        """Test serializing checkpoint to dict."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0)
        checkpoint = Checkpoint(
            id="uuid-123",
            description="Test checkpoint",
            timestamp=timestamp,
            session_id="session-456",
            files_modified=["/file.txt"],
        )

        data = checkpoint.to_dict()

        assert data["id"] == "uuid-123"
        assert data["description"] == "Test checkpoint"
        assert data["timestamp"] == "2024-01-15T10:30:00"
        assert data["session_id"] == "session-456"
        assert data["files_modified"] == ["/file.txt"]

    def test_from_dict(self) -> None:
        """Test deserializing checkpoint from dict."""
        data = {
            "id": "uuid-123",
            "description": "Test checkpoint",
            "timestamp": "2024-01-15T10:30:00",
            "session_id": "session-456",
            "files_modified": ["/file.txt"],
        }

        checkpoint = Checkpoint.from_dict(data)

        assert checkpoint.id == "uuid-123"
        assert checkpoint.description == "Test checkpoint"
        assert checkpoint.timestamp == datetime(2024, 1, 15, 10, 30, 0)
        assert checkpoint.session_id == "session-456"
        assert checkpoint.files_modified == ["/file.txt"]

    def test_from_dict_minimal(self) -> None:
        """Test deserializing checkpoint with minimal data."""
        data = {
            "id": "uuid-123",
            "description": "Minimal",
            "timestamp": "2024-01-15T10:30:00",
        }

        checkpoint = Checkpoint.from_dict(data)

        assert checkpoint.id == "uuid-123"
        assert checkpoint.session_id is None
        assert checkpoint.files_modified == []


# =============================================================================
# CheckpointManager Tests
# =============================================================================


class TestCheckpointManager:
    """Tests for CheckpointManager class."""

    def test_create_manager(self) -> None:
        """Test creating a checkpoint manager."""
        manager = CheckpointManager()
        assert manager.checkpoints == []
        assert manager.current_session_id is None
        assert manager.enable_checkpointing is True

    def test_create_checkpoint(self) -> None:
        """Test creating a checkpoint through manager."""
        manager = CheckpointManager()
        checkpoint = manager.create_checkpoint(
            checkpoint_id="uuid-123",
            description="First checkpoint",
        )

        assert checkpoint.id == "uuid-123"
        assert checkpoint.description == "First checkpoint"
        assert len(manager.checkpoints) == 1

    def test_create_checkpoint_with_session(self) -> None:
        """Test creating checkpoint inherits current session."""
        manager = CheckpointManager(current_session_id="session-abc")
        checkpoint = manager.create_checkpoint(
            checkpoint_id="uuid-123",
            description="With session",
        )

        assert checkpoint.session_id == "session-abc"

    def test_create_checkpoint_override_session(self) -> None:
        """Test creating checkpoint with explicit session."""
        manager = CheckpointManager(current_session_id="session-abc")
        checkpoint = manager.create_checkpoint(
            checkpoint_id="uuid-123",
            description="Override session",
            session_id="session-xyz",
        )

        assert checkpoint.session_id == "session-xyz"

    def test_get_checkpoint(self) -> None:
        """Test getting checkpoint by ID."""
        manager = CheckpointManager()
        manager.create_checkpoint("uuid-1", "First")
        manager.create_checkpoint("uuid-2", "Second")
        manager.create_checkpoint("uuid-3", "Third")

        checkpoint = manager.get_checkpoint("uuid-2")

        assert checkpoint is not None
        assert checkpoint.id == "uuid-2"
        assert checkpoint.description == "Second"

    def test_get_checkpoint_not_found(self) -> None:
        """Test getting non-existent checkpoint."""
        manager = CheckpointManager()
        manager.create_checkpoint("uuid-1", "First")

        checkpoint = manager.get_checkpoint("uuid-999")

        assert checkpoint is None

    def test_get_latest_checkpoint(self) -> None:
        """Test getting the most recent checkpoint."""
        manager = CheckpointManager()
        manager.create_checkpoint("uuid-1", "First")
        manager.create_checkpoint("uuid-2", "Second")
        manager.create_checkpoint("uuid-3", "Third")

        latest = manager.get_latest_checkpoint()

        assert latest is not None
        assert latest.id == "uuid-3"

    def test_get_latest_checkpoint_empty(self) -> None:
        """Test getting latest when no checkpoints exist."""
        manager = CheckpointManager()

        latest = manager.get_latest_checkpoint()

        assert latest is None

    def test_list_checkpoints(self) -> None:
        """Test listing checkpoints in reverse order."""
        manager = CheckpointManager()
        manager.create_checkpoint("uuid-1", "First")
        manager.create_checkpoint("uuid-2", "Second")
        manager.create_checkpoint("uuid-3", "Third")

        checkpoints = manager.list_checkpoints()

        assert len(checkpoints) == 3
        # Most recent first
        assert checkpoints[0].id == "uuid-3"
        assert checkpoints[1].id == "uuid-2"
        assert checkpoints[2].id == "uuid-1"

    def test_list_checkpoints_with_limit(self) -> None:
        """Test listing checkpoints with limit."""
        manager = CheckpointManager()
        for i in range(5):
            manager.create_checkpoint(f"uuid-{i}", f"Checkpoint {i}")

        checkpoints = manager.list_checkpoints(limit=2)

        assert len(checkpoints) == 2
        assert checkpoints[0].id == "uuid-4"  # Most recent
        assert checkpoints[1].id == "uuid-3"

    def test_list_checkpoints_by_session(self) -> None:
        """Test listing checkpoints filtered by session."""
        manager = CheckpointManager()
        manager.create_checkpoint("uuid-1", "Session A", session_id="a")
        manager.create_checkpoint("uuid-2", "Session B", session_id="b")
        manager.create_checkpoint("uuid-3", "Session A", session_id="a")
        manager.create_checkpoint("uuid-4", "Session B", session_id="b")

        checkpoints = manager.list_checkpoints(session_id="a")

        assert len(checkpoints) == 2
        assert all(c.session_id == "a" for c in checkpoints)

    def test_record_file_modification(self) -> None:
        """Test recording file modifications."""
        manager = CheckpointManager()
        manager.create_checkpoint("uuid-1", "Initial")

        manager.record_file_modification("/src/main.py")
        manager.record_file_modification("/src/utils.py")

        latest = manager.get_latest_checkpoint()
        assert latest is not None
        assert "/src/main.py" in latest.files_modified
        assert "/src/utils.py" in latest.files_modified

    def test_record_file_modification_no_duplicates(self) -> None:
        """Test that duplicate file modifications are not recorded."""
        manager = CheckpointManager()
        manager.create_checkpoint("uuid-1", "Initial")

        manager.record_file_modification("/src/main.py")
        manager.record_file_modification("/src/main.py")  # Duplicate

        latest = manager.get_latest_checkpoint()
        assert latest is not None
        assert latest.files_modified.count("/src/main.py") == 1

    def test_record_file_modification_no_checkpoints(self) -> None:
        """Test recording modifications when no checkpoints exist."""
        manager = CheckpointManager()

        # Should not raise
        manager.record_file_modification("/src/main.py")

    def test_clear_checkpoints(self) -> None:
        """Test clearing all checkpoints."""
        manager = CheckpointManager()
        manager.create_checkpoint("uuid-1", "First")
        manager.create_checkpoint("uuid-2", "Second")

        manager.clear_checkpoints()

        assert len(manager.checkpoints) == 0


# =============================================================================
# get_checkpointing_env Tests
# =============================================================================


class TestGetCheckpointingEnv:
    """Tests for get_checkpointing_env function."""

    def test_returns_env_with_checkpointing_enabled(self) -> None:
        """Test that env includes checkpointing variable."""
        env = get_checkpointing_env()

        assert "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING" in env
        assert env["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] == "1"

    def test_preserves_existing_env(self) -> None:
        """Test that existing env vars are preserved."""
        import os

        original_path = os.environ.get("PATH")
        env = get_checkpointing_env()

        assert env.get("PATH") == original_path


# =============================================================================
# CheckpointingOptions Tests
# =============================================================================


class TestCheckpointingOptions:
    """Tests for CheckpointingOptions dataclass."""

    def test_default_values(self) -> None:
        """Test default option values."""
        options = CheckpointingOptions()

        assert options.enabled is False
        assert options.auto_checkpoint_on_task is True
        assert options.keep_count == 10
        assert options.checkpoint_dir is None

    def test_enabled_options(self) -> None:
        """Test enabling checkpointing."""
        options = CheckpointingOptions(
            enabled=True,
            keep_count=5,
        )

        assert options.enabled is True
        assert options.keep_count == 5

    def test_to_sdk_options_disabled(self) -> None:
        """Test SDK options when disabled."""
        options = CheckpointingOptions(enabled=False)

        sdk_options = options.to_sdk_options()

        assert sdk_options == {}

    def test_to_sdk_options_enabled(self) -> None:
        """Test SDK options when enabled."""
        options = CheckpointingOptions(enabled=True)

        sdk_options = options.to_sdk_options()

        assert sdk_options["enable_file_checkpointing"] is True
        assert sdk_options["extra_args"] == {"replay-user-messages": None}


# =============================================================================
# Exception Tests
# =============================================================================


class TestCheckpointExceptions:
    """Tests for checkpoint exceptions."""

    def test_checkpoint_error_base(self) -> None:
        """Test CheckpointError base exception."""
        error = CheckpointError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert isinstance(error, Exception)

    def test_checkpoint_not_found_error(self) -> None:
        """Test CheckpointNotFoundError."""
        error = CheckpointNotFoundError("uuid-123")

        assert error.checkpoint_id == "uuid-123"
        assert "uuid-123" in str(error)
        assert isinstance(error, CheckpointError)

    def test_checkpoint_rewind_error(self) -> None:
        """Test CheckpointRewindError."""
        error = CheckpointRewindError("uuid-456", "Session expired")

        assert error.checkpoint_id == "uuid-456"
        assert error.reason == "Session expired"
        assert "uuid-456" in str(error)
        assert "Session expired" in str(error)
        assert isinstance(error, CheckpointError)
