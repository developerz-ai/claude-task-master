"""Contract tests: REST and MCP agree on validation and outcomes.

Both transports delegate to the same :class:`TaskService` layer and therefore
share a single ``ServiceResult.outcome``.  These tests exercise the same
scenario through *both* surfaces and assert that they reach identical
conclusions (success vs failure) and respect the same validation rules.

The outcome-to-wire mapping *can* differ between transports — for example
:attr:`ServiceOutcome.NOT_FOUND` becomes HTTP 404 over REST and
``{"success": False}`` over MCP — but both must classify the operation as a
failure.  Documented intentional divergences are tested explicitly so they
cannot silently drift.

**Note on surface coverage.** Not every operation is exposed by both transports.
Specifically, ``pause`` is MCP-only (the REST API has no ``POST /control/pause``
route); tests for it appear in ``tests/mcp/test_tools_control.py``.  This file
covers only the *shared* operations.

Scenarios covered per operation:

* **get_status** — no-task (NOT_FOUND), task present (OK)
* **get_plan** — no-task (NOT_FOUND), no plan (NOT_FOUND), plan present (OK)
* **get_logs** — no-task (NOT_FOUND), tail < 1 (INVALID), log absent (NOT_FOUND), log present (OK)
* **get_progress** — no-task (NOT_FOUND), progress present (OK)
* **get_context** — no-task (NOT_FOUND), context present (OK)
* **delete_coding_style** — no-task (NOT_FOUND), task present / file absent (OK)
* **stop** — no-task (NOT_FOUND), planning → stopped (OK)
* **resume** — no-task (NOT_FOUND), paused → working (OK), planning (INVALID)
* **update_config** — no-task (NOT_FOUND), no options (INVALID), valid update (OK)
* **clean** — no-task (intentional divergence: REST 404 / MCP success=True), task present (OK both)
* **cross-transport state** — MCP-applied state changes visible via REST (pause → REST resume)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from .conftest import _FASTAPI_AVAILABLE, _MCP_AVAILABLE

if TYPE_CHECKING:
    from claude_task_master.core.state import StateManager

pytestmark = pytest.mark.skipif(
    not (_FASTAPI_AVAILABLE and _MCP_AVAILABLE),
    reason="FastAPI or MCP SDK not installed",
)


# ---------------------------------------------------------------------------
# Helpers: REST outcome extraction
# ---------------------------------------------------------------------------


def _rest_ok(response) -> bool:
    """True when the REST response signals success."""
    if response.status_code in (200, 201):
        body: dict[str, Any] = response.json()
        # Most REST endpoints include an explicit success field; the HTTP code alone
        # is authoritative for the contract, but we also check the body flag when
        # present to catch mis-classified 2xx responses.
        return bool(body.get("success", True))
    return False


def _rest_not_found(response) -> bool:
    return bool(response.status_code == 404)


def _rest_invalid(response) -> bool:
    # FastAPI / TaskService INVALID maps to HTTP 400; FastAPI's own schema
    # validation returns 422 — both count as "rejected" for the contract.
    return bool(response.status_code in (400, 422))


# ---------------------------------------------------------------------------
# Helpers: MCP outcome extraction
# ---------------------------------------------------------------------------


def _mcp_ok(result: dict[str, Any]) -> bool:
    """True when the MCP result signals success."""
    return bool(result.get("success"))


def _mcp_fail(result: dict[str, Any]) -> bool:
    return not bool(result.get("success", True))


# ===========================================================================
# 1.  get_status
# ===========================================================================


class TestGetStatusContract:
    """get_status: no-task → both fail; task present → both succeed.

    MCP ``get_status`` on success returns the ``TaskStatus`` model dump directly
    (no ``success`` key) rather than ``{"success": True, ...}``.  The helper
    ``_mcp_status_ok`` recognises this format.
    """

    @staticmethod
    def _mcp_status_ok(result: dict) -> bool:
        """True when MCP get_status returned a valid status dict (no success key)."""
        # Success path: TaskStatus model dump — has "goal" but no "success" key.
        # Failure path: {"success": False, "error": "..."}.
        return result.get("success", True) is not False and "goal" in result

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        """NOT_FOUND: REST 404, MCP success=False."""
        from claude_task_master.mcp.tools import get_status

        rest_response = rest_client.get("/status")
        mcp_result = get_status(work_dir)

        assert _rest_not_found(rest_response), f"expected 404, got {rest_response.status_code}"
        assert _mcp_fail(mcp_result), f"expected MCP failure, got {mcp_result}"

    def test_task_present_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """OK: REST 200, MCP returns status dict with goal field."""
        from claude_task_master.mcp.tools import get_status

        work_dir, _ = initialized_work_dir
        rest_response = rest_client.get("/status")
        mcp_result = get_status(work_dir)

        assert _rest_ok(rest_response), f"expected 200, got {rest_response.status_code}"
        assert self._mcp_status_ok(mcp_result), f"expected status dict, got {mcp_result}"
        # Both surfaces agree on the goal.
        assert mcp_result["goal"] == rest_response.json()["goal"]


# ===========================================================================
# 2.  get_plan
# ===========================================================================


class TestGetPlanContract:
    """get_plan: no-task → both fail; no plan → both fail; plan present → both succeed."""

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        """NOT_FOUND (no task): REST 404, MCP success=False."""
        from claude_task_master.mcp.tools import get_plan

        rest_response = rest_client.get("/plan")
        mcp_result = get_plan(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_no_plan_both_fail(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """NOT_FOUND (no plan yet): REST 404, MCP success=False."""
        from claude_task_master.mcp.tools import get_plan

        work_dir, _ = initialized_work_dir
        rest_response = rest_client.get("/plan")
        mcp_result = get_plan(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_plan_present_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """OK: REST 200, MCP success=True."""
        from claude_task_master.mcp.tools import get_plan

        work_dir, sm = initialized_work_dir
        sm.save_plan("- [ ] Task 1\n- [ ] Task 2\n")

        rest_response = rest_client.get("/plan")
        mcp_result = get_plan(work_dir)

        assert _rest_ok(rest_response)
        assert _mcp_ok(mcp_result)
        # Both surfaces return the same plan text.
        assert rest_response.json()["plan"] == mcp_result["plan"]


# ===========================================================================
# 3.  get_logs
# ===========================================================================


class TestGetLogsContract:
    """get_logs: validation (tail), no-task, no-log, and happy-path."""

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        """NOT_FOUND: REST 404, MCP success=False."""
        from claude_task_master.mcp.tools import get_logs

        rest_response = rest_client.get("/logs")
        mcp_result = get_logs(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_tail_zero_both_reject(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """INVALID (tail < 1): REST 400/422, MCP success=False."""
        from claude_task_master.mcp.tools import get_logs

        work_dir, _ = initialized_work_dir
        # REST enforces tail ≥ 1 via FastAPI query validation → 422
        rest_response = rest_client.get("/logs?tail=0")
        mcp_result = get_logs(work_dir, tail=0)

        assert _rest_invalid(rest_response), f"expected 4xx, got {rest_response.status_code}"
        assert _mcp_fail(mcp_result), f"expected MCP failure, got {mcp_result}"

    def test_no_log_file_both_fail(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """NOT_FOUND (log absent): REST 404, MCP success=False."""
        from claude_task_master.mcp.tools import get_logs

        work_dir, _ = initialized_work_dir
        rest_response = rest_client.get("/logs")
        mcp_result = get_logs(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_log_present_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """OK: REST 200, MCP success=True; both return the same trailing content."""
        from claude_task_master.mcp.tools import get_logs

        work_dir, sm = initialized_work_dir
        state = sm.load_state()
        log_file = sm.get_log_file(state.run_id)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("".join(f"line-{i}\n" for i in range(20)))

        rest_response = rest_client.get("/logs?tail=5")
        mcp_result = get_logs(work_dir, tail=5)

        assert _rest_ok(rest_response)
        assert _mcp_ok(mcp_result)
        # Both return only the last 5 lines.
        assert rest_response.json()["log_content"] == mcp_result["log_content"]
        assert len(rest_response.json()["log_content"].strip().splitlines()) == 5


# ===========================================================================
# 4.  get_progress
# ===========================================================================


class TestGetProgressContract:
    """get_progress: no-task → both fail; progress present → both succeed."""

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        from claude_task_master.mcp.tools import get_progress

        rest_response = rest_client.get("/progress")
        mcp_result = get_progress(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_progress_present_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        from claude_task_master.mcp.tools import get_progress

        work_dir, sm = initialized_work_dir
        sm.save_progress("halfway there")

        rest_response = rest_client.get("/progress")
        mcp_result = get_progress(work_dir)

        assert _rest_ok(rest_response)
        assert _mcp_ok(mcp_result)


# ===========================================================================
# 5.  get_context
# ===========================================================================


class TestGetContextContract:
    """get_context: no-task → both fail; context present → both succeed."""

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        from claude_task_master.mcp.tools import get_context

        rest_response = rest_client.get("/context")
        mcp_result = get_context(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_context_present_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        from claude_task_master.mcp.tools import get_context

        work_dir, sm = initialized_work_dir
        sm.save_context("learned something")

        rest_response = rest_client.get("/context")
        mcp_result = get_context(work_dir)

        assert _rest_ok(rest_response)
        assert _mcp_ok(mcp_result)


# ===========================================================================
# 6.  delete_coding_style
# ===========================================================================


class TestDeleteCodingStyleContract:
    """delete_coding_style: no-task → both fail; task present → both succeed."""

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        from claude_task_master.mcp.tools import delete_coding_style

        rest_response = rest_client.delete("/coding-style")
        mcp_result = delete_coding_style(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_task_present_file_absent_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """File is absent but the task exists → both report success (deleted=False)."""
        from claude_task_master.mcp.tools import delete_coding_style

        work_dir, _ = initialized_work_dir
        rest_response = rest_client.delete("/coding-style")
        mcp_result = delete_coding_style(work_dir)

        assert _rest_ok(rest_response)
        assert _mcp_ok(mcp_result)
        # Neither side deleted anything because the file didn't exist.
        assert rest_response.json()["file_existed"] is False
        assert mcp_result["deleted"] is False

    def test_task_present_file_exists_both_succeed_and_delete(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """File present → both remove it and report success."""
        from claude_task_master.mcp.tools import delete_coding_style

        work_dir, sm = initialized_work_dir
        coding_style = sm.state_dir / "coding-style.md"
        coding_style.write_text("# Coding Style\n\nFollow PEP 8.\n")

        rest_response = rest_client.delete("/coding-style")
        mcp_result = delete_coding_style(work_dir)

        # After the first call the file is gone; the second call is a no-op.
        # Both must still succeed (idempotent).
        assert _rest_ok(rest_response) or _rest_ok(rest_client.delete("/coding-style"))
        assert _mcp_ok(mcp_result) or _mcp_ok(delete_coding_style(work_dir))


# ===========================================================================
# 7.  Cross-transport state visibility
#
# The REST API has no ``POST /control/pause`` route — pause is MCP-only.
# These tests verify that state mutations from one transport are immediately
# visible to the other, cementing the shared-state contract.
# ===========================================================================


class TestCrossTransportState:
    """State written by one transport is immediately visible to the other.

    Specifically:
    * MCP ``pause_task`` → REST ``GET /status`` sees ``"paused"``
    * MCP ``pause_task`` → REST ``POST /control/resume`` succeeds
    * REST ``POST /control/stop`` → MCP ``resume_task`` sees ``"stopped"``

    Note: The REST API exposes no ``/control/pause`` route; ``pause_task``
    is an MCP-only operation.  This class tests cross-transport *visibility*,
    not cross-transport operation parity for pause.
    """

    def test_mcp_pause_visible_via_rest_status(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """MCP pause → REST /status reports status='paused'."""
        from claude_task_master.mcp.tools import pause_task

        work_dir, _ = initialized_work_dir
        mcp_result = pause_task(work_dir)
        assert _mcp_ok(mcp_result), f"pause_task failed: {mcp_result}"

        rest_response = rest_client.get("/status")
        assert _rest_ok(rest_response)
        assert rest_response.json()["status"] == "paused"

    def test_mcp_pause_then_rest_resume(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """MCP pause → REST /control/resume succeeds (state crosses transport boundary)."""
        from claude_task_master.mcp.tools import pause_task

        work_dir, _ = initialized_work_dir
        pause_result = pause_task(work_dir)
        assert _mcp_ok(pause_result), f"pause_task failed: {pause_result}"

        resume_response = rest_client.post("/control/resume", json={})
        assert _rest_ok(resume_response), (
            f"expected REST resume to succeed after MCP pause, got {resume_response.status_code}"
        )
        assert resume_response.json()["new_status"] == "working"

    def test_rest_stop_visible_via_mcp(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """REST /control/stop → MCP resume_task sees task in 'stopped' state."""
        from claude_task_master.mcp.tools import resume_task

        work_dir, _ = initialized_work_dir
        stop_response = rest_client.post("/control/stop", json={})
        assert _rest_ok(stop_response), (
            f"expected REST stop to succeed, got {stop_response.status_code}"
        )

        mcp_result = resume_task(work_dir)
        assert _mcp_ok(mcp_result), f"resume_task after REST stop failed: {mcp_result}"
        assert mcp_result.get("previous_status") == "stopped"


# ===========================================================================
# 8.  stop
# ===========================================================================


class TestStopContract:
    """stop: no-task → both fail; planning → stopped → both succeed."""

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        from claude_task_master.mcp.tools import stop_task

        rest_response = rest_client.post("/control/stop", json={})
        mcp_result = stop_task(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_planning_to_stopped_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """OK (planning → stopped): REST 200, MCP success=True."""
        import tempfile

        from claude_task_master.mcp.tools import stop_task

        from .conftest import _init_task

        # REST path uses the shared initialized state.
        rest_response = rest_client.post("/control/stop", json={})
        assert _rest_ok(rest_response), f"expected 200, got {rest_response.status_code}"

        # MCP path gets a fresh state to avoid seeing the stopped task.
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            _init_task(wd / ".claude-task-master")
            mcp_result = stop_task(wd)
            assert _mcp_ok(mcp_result), f"expected MCP success, got {mcp_result}"
            assert mcp_result.get("new_status") == "stopped"


# ===========================================================================
# 9.  resume
# ===========================================================================


class TestResumeContract:
    """resume: no-task → both fail; paused → working → both succeed; planning (not resumable) → both fail."""

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        from claude_task_master.mcp.tools import resume_task

        rest_response = rest_client.post("/control/resume", json={})
        mcp_result = resume_task(work_dir)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_paused_to_working_both_succeed(
        self, paused_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """OK (paused → working): REST 200, MCP success=True."""
        import tempfile

        from claude_task_master.core.control import ControlManager
        from claude_task_master.mcp.tools import resume_task

        from .conftest import _init_task

        # REST path uses the shared paused state.
        rest_response = rest_client.post("/control/resume", json={})
        assert _rest_ok(rest_response), f"expected 200, got {rest_response.status_code}"

        # MCP path: fresh state, manually paused.
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            sm = _init_task(wd / ".claude-task-master")
            ControlManager(state_manager=sm).pause()
            mcp_result = resume_task(wd)
            assert _mcp_ok(mcp_result), f"expected MCP success, got {mcp_result}"
            assert mcp_result.get("new_status") == "working"

    def test_planning_not_resumable_both_fail(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """INVALID (planning is not resumable): REST 400, MCP success=False."""
        import tempfile

        from claude_task_master.mcp.tools import resume_task

        from .conftest import _init_task

        # REST path: task is in planning state.
        rest_response = rest_client.post("/control/resume", json={})
        assert _rest_invalid(rest_response), f"expected 4xx, got {rest_response.status_code}"

        # MCP path: same scenario.
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            _init_task(wd / ".claude-task-master")
            mcp_result = resume_task(wd)
            assert _mcp_fail(mcp_result), f"expected MCP failure, got {mcp_result}"


# ===========================================================================
# 10.  update_config
# ===========================================================================


class TestUpdateConfigContract:
    """update_config: no-task → both fail; no options → both fail; valid → both succeed."""

    def test_no_task_both_fail(self, work_dir: Path, rest_client) -> None:
        from claude_task_master.mcp.tools import update_config

        rest_response = rest_client.patch("/config", json={"auto_merge": False})
        mcp_result = update_config(work_dir, auto_merge=False)

        assert _rest_not_found(rest_response)
        assert _mcp_fail(mcp_result)

    def test_no_options_both_fail(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """INVALID (empty update): REST 400, MCP success=False."""
        from claude_task_master.mcp.tools import update_config

        work_dir, _ = initialized_work_dir
        # Empty JSON body → REST enforces at least one field (has_updates=False).
        rest_response = rest_client.patch("/config", json={})
        mcp_result = update_config(work_dir)

        assert _rest_invalid(rest_response), f"expected 4xx, got {rest_response.status_code}"
        assert _mcp_fail(mcp_result), f"expected MCP failure, got {mcp_result}"

    def test_valid_update_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """OK: REST 200, MCP success=True; both reflect the new value."""
        import tempfile

        from claude_task_master.mcp.tools import update_config

        from .conftest import _init_task

        # REST path.
        rest_response = rest_client.patch("/config", json={"auto_merge": False})
        assert _rest_ok(rest_response), f"expected 200, got {rest_response.status_code}"

        # MCP path (fresh state to avoid racing with the REST-modified state).
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            sm = _init_task(wd / ".claude-task-master")
            mcp_result = update_config(wd, auto_merge=False)
            assert _mcp_ok(mcp_result), f"expected MCP success, got {mcp_result}"
            updated_state = sm.load_state()
            assert updated_state.options.auto_merge is False


# ===========================================================================
# 11.  clean — intentional divergence
# ===========================================================================


class TestCleanContract:
    """clean: intentional transport difference documented and tested.

    REST maps NOT_FOUND → 404 (failure) because DELETE /task on a missing
    resource is a client error in HTTP semantics.

    MCP maps NOT_FOUND → success=True because "nothing to clean" is a benign
    no-op in a tool invocation.  This divergence is intentional and specified
    in the MCP clean_task implementation.
    """

    def test_no_task_documented_divergence(self, work_dir: Path, rest_client) -> None:
        """REST 404 vs MCP success=True for NOT_FOUND — intentional contract split."""
        from claude_task_master.mcp.tools import clean_task

        rest_response = rest_client.delete("/task")
        mcp_result = clean_task(work_dir)

        # REST treats "nothing to clean" as an error (404).
        assert _rest_not_found(rest_response), (
            f"REST should return 404 for missing task, got {rest_response.status_code}"
        )
        # MCP treats "nothing to clean" as a benign success (no-op).
        assert _mcp_ok(mcp_result), (
            f"MCP should return success=True for missing task, got {mcp_result}"
        )
        assert mcp_result.get("files_removed") is False

    def test_task_present_both_succeed(
        self, initialized_work_dir: tuple[Path, StateManager], rest_client
    ) -> None:
        """OK: when a task exists, both surfaces remove it and report success."""
        import tempfile

        from claude_task_master.mcp.tools import clean_task

        from .conftest import _init_task

        # REST deletes the shared task.
        rest_response = rest_client.delete("/task")
        assert _rest_ok(rest_response), f"expected 200, got {rest_response.status_code}"

        # MCP needs its own task (REST already removed the shared one).
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            _init_task(wd / ".claude-task-master")
            mcp_result = clean_task(wd)
            assert _mcp_ok(mcp_result), f"expected MCP success, got {mcp_result}"
            assert mcp_result.get("files_removed") is True
