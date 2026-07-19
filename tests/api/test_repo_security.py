"""Security tests for repo-setup REST endpoints.

Covers the unauthenticated-RCE-chain hardening:
- Repo endpoints return 403 when authentication is disabled.
- ``target_dir``/``work_dir`` escapes are rejected with 422.
- Setup scripts run only when explicitly opted in.
- ``run_server`` refuses to bind non-localhost without enforceable auth.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def confine_base(monkeypatch, temp_dir):
    """Confine the workspace base to a temp dir (validator + tools agree)."""
    import claude_task_master.mcp.tools as tools_mod

    monkeypatch.setattr(tools_mod, "DEFAULT_WORKSPACE_BASE", temp_dir)
    return temp_dir


@pytest.fixture
def disable_auth(monkeypatch):
    """Report authentication as disabled at the route boundary."""
    import claude_task_master.api.routes_repo as routes_mod

    monkeypatch.setattr(routes_mod, "is_auth_enabled", lambda: False)


@pytest.fixture
def enable_auth(monkeypatch):
    """Report authentication as enabled at the route and tool boundaries."""
    import claude_task_master.api.routes_repo as routes_mod
    import claude_task_master.mcp.tools as tools_mod

    monkeypatch.setattr(routes_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(tools_mod, "is_auth_enabled", lambda: True)


# =============================================================================
# Unauthenticated refusal (403)
# =============================================================================


class TestRepoEndpointsRequireAuth:
    """Repo endpoints must refuse with 403 when auth is disabled."""

    def test_clone_refused_without_auth(self, api_client, disable_auth):
        """POST /repo/clone returns 403 without authentication."""
        response = api_client.post("/repo/clone", json={"url": "https://github.com/test/repo.git"})

        assert response.status_code == 403
        assert response.json()["error"] == "authentication_required"

    def test_setup_refused_without_auth(self, api_client, disable_auth, confine_base):
        """POST /repo/setup returns 403 without authentication."""
        response = api_client.post("/repo/setup", json={"work_dir": str(confine_base / "repo")})

        assert response.status_code == 403
        assert response.json()["error"] == "authentication_required"

    def test_plan_refused_without_auth(self, api_client, disable_auth, confine_base):
        """POST /repo/plan returns 403 without authentication."""
        response = api_client.post(
            "/repo/plan",
            json={"work_dir": str(confine_base / "repo"), "goal": "Do work"},
        )

        assert response.status_code == 403
        assert response.json()["error"] == "authentication_required"


# =============================================================================
# Path-escape rejection (422)
# =============================================================================


class TestRepoPathEscapeRejected:
    """Escaping paths are rejected by request validation (422)."""

    def test_clone_target_escape_rejected(self, api_client, confine_base):
        """A target_dir outside the workspace base is a 422 validation error."""
        response = api_client.post(
            "/repo/clone",
            json={"url": "https://github.com/test/repo.git", "target_dir": "/tmp/evil"},
        )

        assert response.status_code == 422

    def test_setup_work_dir_escape_rejected(self, api_client, confine_base):
        """A work_dir outside the workspace base is a 422 validation error."""
        response = api_client.post("/repo/setup", json={"work_dir": "/etc"})

        assert response.status_code == 422

    def test_plan_work_dir_escape_rejected(self, api_client, confine_base):
        """A work_dir outside the workspace base is a 422 validation error."""
        response = api_client.post("/repo/plan", json={"work_dir": "/etc", "goal": "Do work"})

        assert response.status_code == 422


# =============================================================================
# Setup-script opt-in
# =============================================================================


class TestSetupScriptOptIn:
    """Setup scripts are skipped unless run_setup_scripts is requested."""

    def test_scripts_skipped_by_default(self, api_client, enable_auth, confine_base):
        """POST /repo/setup does not run setup scripts by default."""
        repo_dir = confine_base / "repo-scripts"
        repo_dir.mkdir(parents=True)
        (repo_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        scripts_dir = repo_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "setup.sh").write_text("#!/bin/bash\necho hi\n")
        (scripts_dir / "setup.sh").chmod(0o755)

        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value="/usr/bin/uv"):
                response = api_client.post("/repo/setup", json={"work_dir": str(repo_dir)})

        assert response.status_code == 200
        assert response.json()["setup_scripts_run"] == []


# =============================================================================
# run_server refuses public bind without auth
# =============================================================================


class TestRunServerPublicBind:
    """run_server must fail closed on non-localhost binds without auth."""

    def test_exits_on_public_bind_without_auth(self, monkeypatch):
        """Binding to 0.0.0.0 without enforceable auth raises SystemExit."""
        pytest.importorskip("uvicorn")
        from claude_task_master.api import server as server_mod

        monkeypatch.setattr(server_mod, "is_auth_enabled", lambda: False)

        with patch("uvicorn.run") as mock_uvicorn_run:
            with pytest.raises(SystemExit):
                server_mod.run_server(host="0.0.0.0")

        mock_uvicorn_run.assert_not_called()

    def test_allows_localhost_bind_without_auth(self, monkeypatch):
        """Binding to localhost without auth is allowed (no SystemExit)."""
        pytest.importorskip("uvicorn")
        from claude_task_master.api import server as server_mod

        monkeypatch.setattr(server_mod, "is_auth_enabled", lambda: False)

        with (
            patch("uvicorn.run") as mock_uvicorn_run,
            patch.object(server_mod, "create_app", return_value=MagicMock()),
        ):
            server_mod.run_server(host="127.0.0.1")

        mock_uvicorn_run.assert_called_once()


# =============================================================================
# plan_repo works from a running event loop
# =============================================================================


class TestPlanRepoFromRunningLoop:
    """POST /repo/plan offloads plan_repo to a worker thread — no event-loop conflict.

    The original bug: plan_repo called asyncio.get_event_loop().run_until_complete()
    directly inside the async route handler, raising RuntimeError because there was
    already a running loop.  The fix wraps the call with
    ``await anyio.to_thread.run_sync(partial(plan_repo, ...))`` so plan_repo runs
    in a worker thread where it may safely create and drive its own event loop.
    """

    def test_plan_repo_can_start_own_event_loop(self, api_client, enable_auth, confine_base):
        """plan_repo runs in a worker thread — asyncio.new_event_loop() succeeds there.

        The fake plan_repo does exactly what run_async_with_cleanup does: it creates
        a fresh event loop and calls run_until_complete.  If anyio.to_thread.run_sync
        is missing and plan_repo is invoked directly from the async handler, this
        would raise RuntimeError("This event loop is already running"); the endpoint
        would catch it and return 500/400.  Thread-offload makes it return 200.
        """
        repo_dir = confine_base / "plan-loop-repo"
        repo_dir.mkdir(parents=True)

        def _plan_with_own_loop(work_dir, goal, model="opus"):
            """Simulate run_async_with_cleanup: start a fresh event loop from a thread."""
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(asyncio.sleep(0))
            finally:
                loop.close()
            return {
                "success": True,
                "message": "Plan created",
                "work_dir": str(work_dir),
                "goal": goal,
                "plan": "- [ ] Task 1",
                "criteria": "All tests pass",
                "run_id": "test-thread-loop-001",
            }

        with patch(
            "claude_task_master.mcp.tools.plan_repo",
            side_effect=_plan_with_own_loop,
        ):
            response = api_client.post(
                "/repo/plan",
                json={"work_dir": str(repo_dir), "goal": "Write a test suite"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["run_id"] == "test-thread-loop-001"
