"""Unit tests for the repository service facade and its result classifier."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from claude_task_master.core.services.repo_service import RepoService, _classify_repo_result
from claude_task_master.core.services.results import ServiceOutcome


class TestClassifyRepoResult:
    """Mapping a tool's result dict onto a typed outcome."""

    def test_success_is_ok_and_preserves_dict(self) -> None:
        """A successful tool dict maps to OK with the dict kept as ``data``."""
        raw = {"success": True, "message": "cloned", "target_dir": "/ws/repo"}
        result = _classify_repo_result(raw)
        assert result.outcome is ServiceOutcome.OK
        assert result.data is raw
        assert result.message == "cloned"

    def test_authentication_required_is_forbidden(self) -> None:
        """The auth sentinel maps to FORBIDDEN (HTTP 403)."""
        raw = {"success": False, "message": "disabled", "error": "authentication_required"}
        result = _classify_repo_result(raw)
        assert result.outcome is ServiceOutcome.FORBIDDEN
        assert result.error == "authentication_required"

    def test_path_outside_workspace_is_invalid(self) -> None:
        """A confinement escape maps to INVALID (HTTP 400)."""
        raw = {"success": False, "message": "escape", "error": "path_outside_workspace"}
        assert _classify_repo_result(raw).outcome is ServiceOutcome.INVALID

    def test_missing_directory_error_is_not_found(self) -> None:
        """An explicit "not found" error maps to NOT_FOUND (HTTP 404)."""
        raw = {"success": False, "message": "gone", "error": "Work directory not found"}
        assert _classify_repo_result(raw).outcome is ServiceOutcome.NOT_FOUND

    def test_does_not_exist_message_is_not_found(self) -> None:
        """A "does not exist" message (no error field) maps to NOT_FOUND."""
        raw = {"success": False, "message": "Directory does not exist: /ws/x"}
        assert _classify_repo_result(raw).outcome is ServiceOutcome.NOT_FOUND

    def test_generic_failure_is_invalid(self) -> None:
        """Any other failure maps to INVALID (HTTP 400)."""
        raw = {"success": False, "message": "Clone failed", "error": "boom"}
        result = _classify_repo_result(raw)
        assert result.outcome is ServiceOutcome.INVALID
        assert result.error == "boom"


class TestRepoServiceDelegation:
    """The async facade offloads to the tool impl and classifies the result."""

    async def test_clone_offloads_and_classifies(self) -> None:
        """``clone`` calls the tool impl in a worker thread and returns a typed result."""
        fake = MagicMock(return_value={"success": True, "message": "ok", "target_dir": "/ws/r"})
        with patch("claude_task_master.mcp.tools.clone_repo", fake):
            result = await RepoService().clone("https://example.com/r.git", branch="main")

        fake.assert_called_once_with("https://example.com/r.git", None, "main")
        assert result.outcome is ServiceOutcome.OK
        assert result.data["target_dir"] == "/ws/r"

    async def test_setup_forwards_run_setup_scripts(self) -> None:
        """``setup`` forwards the opt-in flag and classifies a not-found failure."""
        fake = MagicMock(
            return_value={"success": False, "message": "nope", "error": "Work directory not found"}
        )
        with patch("claude_task_master.mcp.tools.setup_repo", fake):
            result = await RepoService().setup("/ws/repo", run_setup_scripts=True)

        fake.assert_called_once_with("/ws/repo", run_setup_scripts=True)
        assert result.outcome is ServiceOutcome.NOT_FOUND
