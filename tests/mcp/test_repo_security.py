"""Security tests for repo-setup MCP tools.

Covers the unauthenticated-RCE-chain hardening:
- Repo tools refuse to run when authentication is disabled.
- ``target_dir``/``work_dir`` are confined under the workspace base.
- Setup scripts run only when explicitly opted in.
- ``clean_task`` refuses to delete state directories outside ``work_dir``.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


def _disable_auth(monkeypatch):
    """Make ``is_auth_enabled`` report authentication as disabled."""
    import claude_task_master.mcp.tools as tools_mod

    monkeypatch.setattr(tools_mod, "is_auth_enabled", lambda: False)


def _enable_auth_confined(monkeypatch, base):
    """Enable auth and confine the workspace base to *base*."""
    import claude_task_master.mcp.tools as tools_mod

    monkeypatch.setattr(tools_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(tools_mod, "DEFAULT_WORKSPACE_BASE", base)


class TestRepoToolsRequireAuth:
    """Repo tools must refuse when authentication is not configured."""

    def test_clone_repo_refused_without_auth(self, monkeypatch, temp_dir):
        """clone_repo refuses and never touches the filesystem without auth."""
        from claude_task_master.mcp.tools import clone_repo

        _disable_auth(monkeypatch)
        result = clone_repo("https://github.com/test/repo.git", target_dir=str(temp_dir / "r"))

        assert result["success"] is False
        assert result["error"] == "authentication_required"
        assert not (temp_dir / "r").exists()

    def test_setup_repo_refused_without_auth(self, monkeypatch, temp_dir):
        """setup_repo refuses without auth."""
        from claude_task_master.mcp.tools import setup_repo

        _disable_auth(monkeypatch)
        result = setup_repo(str(temp_dir))

        assert result["success"] is False
        assert result["error"] == "authentication_required"

    def test_plan_repo_refused_without_auth(self, monkeypatch, temp_dir):
        """plan_repo refuses without auth."""
        from claude_task_master.mcp.tools import plan_repo

        _disable_auth(monkeypatch)
        result = plan_repo(str(temp_dir), goal="Do work")

        assert result["success"] is False
        assert result["error"] == "authentication_required"


class TestRepoPathConfinement:
    """Repo tools must confine paths under the workspace base."""

    def test_clone_repo_rejects_absolute_escape(self, monkeypatch, temp_dir):
        """clone_repo rejects a target_dir outside the workspace base."""
        from claude_task_master.mcp.tools import clone_repo

        _enable_auth_confined(monkeypatch, temp_dir / "workspace")
        result = clone_repo("https://github.com/test/repo.git", target_dir="/tmp/evil-clone")

        assert result["success"] is False
        assert result["error"] == "path_outside_workspace"

    def test_clone_repo_rejects_dotdot_escape(self, monkeypatch, temp_dir):
        """clone_repo rejects a ``..`` traversal escaping the workspace base."""
        from claude_task_master.mcp.tools import clone_repo

        base = temp_dir / "workspace"
        base.mkdir()
        _enable_auth_confined(monkeypatch, base)
        result = clone_repo(
            "https://github.com/test/repo.git",
            target_dir=str(base / ".." / "escape"),
        )

        assert result["success"] is False
        assert result["error"] == "path_outside_workspace"

    def test_setup_repo_rejects_escape(self, monkeypatch, temp_dir):
        """setup_repo rejects a work_dir outside the workspace base."""
        from claude_task_master.mcp.tools import setup_repo

        _enable_auth_confined(monkeypatch, temp_dir / "workspace")
        result = setup_repo("/etc")

        assert result["success"] is False
        assert result["error"] == "path_outside_workspace"

    def test_plan_repo_rejects_escape(self, monkeypatch, temp_dir):
        """plan_repo rejects a work_dir outside the workspace base."""
        from claude_task_master.mcp.tools import plan_repo

        _enable_auth_confined(monkeypatch, temp_dir / "workspace")
        result = plan_repo("/etc", goal="Do work")

        assert result["success"] is False
        assert result["error"] == "path_outside_workspace"


class TestSetupScriptOptIn:
    """Setup scripts run only when explicitly opted in."""

    def _make_repo_with_script(self, base):
        """Create a repo under *base* whose setup.sh touches a sentinel file."""
        base.mkdir(parents=True, exist_ok=True)
        repo = base / "repo"
        repo.mkdir()
        sentinel = repo / "SENTINEL"
        script = repo / "setup.sh"
        script.write_text(f"#!/bin/bash\ntouch '{sentinel}'\n")
        script.chmod(0o755)
        return repo, sentinel

    def test_scripts_skipped_by_default(self, monkeypatch, temp_dir):
        """Setup scripts are detected but not executed by default."""
        from claude_task_master.mcp.tools import setup_repo

        base = temp_dir / "workspace"
        _enable_auth_confined(monkeypatch, base)
        repo, sentinel = self._make_repo_with_script(base)

        result = setup_repo(str(repo))

        assert result["setup_scripts_run"] == []
        assert not sentinel.exists()
        assert any("skipped" in step.lower() for step in result["steps_completed"])

    def test_scripts_run_when_opted_in(self, monkeypatch, temp_dir):
        """Setup scripts execute when run_setup_scripts=True."""
        from claude_task_master.mcp.tools import setup_repo

        base = temp_dir / "workspace"
        _enable_auth_confined(monkeypatch, base)
        repo, sentinel = self._make_repo_with_script(base)

        result = setup_repo(str(repo), run_setup_scripts=True)

        assert "setup.sh" in result["setup_scripts_run"]
        assert sentinel.exists()


class TestCleanTaskConfinement:
    """clean_task must not delete directories outside work_dir."""

    def test_refuses_state_dir_outside_work_dir(self, temp_dir):
        """clean_task refuses a state_dir that escapes work_dir and deletes nothing."""
        from claude_task_master.mcp.tools import clean_task

        work_dir = temp_dir / "work"
        work_dir.mkdir()

        outside = temp_dir / "outside"
        outside.mkdir()
        marker = outside / "IMPORTANT.txt"
        marker.write_text("do not delete")
        (outside / "state.json").write_text("{}")

        result = clean_task(work_dir, force=True, state_dir=str(outside))

        assert result["success"] is False
        assert "outside" in result["message"].lower()
        assert marker.exists()  # nothing was deleted
