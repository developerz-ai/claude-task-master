"""Transport-neutral repository operations shared by REST and MCP.

The repo operations -- clone, setup, plan -- are blocking and subprocess- or
agent-heavy, so every caller must offload them to a worker thread to keep its
event loop responsive. Previously that ``anyio.to_thread`` wrapping was copied
into both :mod:`claude_task_master.api.routes_repo` and
:mod:`claude_task_master.mcp.server`, and each caller then string-sniffed the
returned ``dict`` to choose a status code.

:class:`RepoService` centralises the offloading and returns a typed
:class:`~claude_task_master.core.services.results.ServiceResult` so REST maps the
outcome to an HTTP status code and MCP forwards the raw payload. The result's
``data`` is the underlying tool dict verbatim, so the MCP transport stays
byte-for-byte identical.

Path confinement and the authentication gate live in the underlying sync
implementations (they read ``DEFAULT_WORKSPACE_BASE`` / ``is_auth_enabled`` from
:mod:`claude_task_master.mcp.tools` so operators and tests can override them),
which this facade delegates to at call time. The heavy sync bodies still live in
:mod:`claude_task_master.mcp.tools` pending their relocation in the file-split
slice; the delegation is intentionally lazy so importing this module never pulls
in the MCP layer.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import anyio

from claude_task_master.core.services.results import ServiceResult

if TYPE_CHECKING:
    from typing import Any

# Substrings in a failed tool result's ``error``/``message`` that mean "the
# target path does not exist" -- mapped to NOT_FOUND (HTTP 404) rather than a
# generic invalid request. Matches the classification the REST routes applied
# inline before this service existed.
_NOT_FOUND_MARKERS = ("not found", "does not exist")


def _classify_repo_result(raw: dict[str, Any]) -> ServiceResult:
    """Map a repo tool's result ``dict`` onto a typed :class:`ServiceResult`.

    The sync tool implementations report success/failure via a ``success`` flag
    plus ``error``/``message`` strings. This is the single place that decision is
    turned into a transport-neutral outcome; the raw dict is preserved as
    ``data`` so each transport can still read every field it needs.

    Args:
        raw: The dict returned by a ``clone_repo``/``setup_repo``/``plan_repo``
            call.

    Returns:
        ``OK`` on success; ``FORBIDDEN`` when authentication was required;
        ``INVALID`` for a path-confinement escape or a generic failure; or
        ``NOT_FOUND`` when the target directory is missing.
    """
    message = str(raw.get("message") or "")
    error = raw.get("error")

    if raw.get("success"):
        return ServiceResult.ok(data=raw, message=message)

    error_str = str(error or "")
    if error == "authentication_required":
        return ServiceResult.forbidden(data=raw, message=message, error=error_str)
    if error == "path_outside_workspace":
        return ServiceResult.invalid(data=raw, message=message, error=error_str)

    haystack = f"{error_str} {message}".lower()
    if any(marker in haystack for marker in _NOT_FOUND_MARKERS):
        return ServiceResult.not_found(data=raw, message=message, error=error_str)

    return ServiceResult.invalid(data=raw, message=message, error=error_str or None)


class RepoService:
    """Path-confined, thread-offloaded repository operations.

    Stateless: a single instance can serve every request. Each method offloads
    the blocking work to a worker thread via ``anyio.to_thread`` and returns a
    typed :class:`ServiceResult` whose ``data`` is the underlying tool dict.
    """

    async def clone(
        self,
        url: str,
        target_dir: str | None = None,
        branch: str | None = None,
    ) -> ServiceResult:
        """Clone a git repository into the confined workspace.

        Args:
            url: Git repository URL (HTTPS or SSH).
            target_dir: Optional destination, confined to the workspace base.
            branch: Optional branch to check out after cloning.

        Returns:
            A :class:`ServiceResult`; ``data`` carries ``repo_url``,
            ``target_dir``, ``branch`` and, on failure, ``error``.
        """
        from claude_task_master.mcp import tools

        raw = await anyio.to_thread.run_sync(partial(tools.clone_repo, url, target_dir, branch))
        return _classify_repo_result(raw)

    async def setup(self, work_dir: str, run_setup_scripts: bool = False) -> ServiceResult:
        """Set up a cloned repository for development.

        Args:
            work_dir: Repository path, confined to the workspace base.
            run_setup_scripts: Opt in to executing repo-supplied setup scripts
                (disabled by default -- running untrusted scripts is an RCE risk).

        Returns:
            A :class:`ServiceResult`; ``data`` carries ``steps_completed``,
            ``venv_path``, ``dependencies_installed`` and ``setup_scripts_run``.
        """
        from claude_task_master.mcp import tools

        raw = await anyio.to_thread.run_sync(
            partial(tools.setup_repo, work_dir, run_setup_scripts=run_setup_scripts)
        )
        return _classify_repo_result(raw)

    async def plan(self, work_dir: str, goal: str, model: str = "opus") -> ServiceResult:
        """Create a read-only plan for a repository.

        Offloaded to a worker thread so the underlying agent can drive its own
        event loop without colliding with the caller's running loop.

        Args:
            work_dir: Repository path, confined to the workspace base.
            goal: The goal to plan for.
            model: Model identifier for planning (default ``"opus"``).

        Returns:
            A :class:`ServiceResult`; ``data`` carries ``plan``, ``criteria`` and
            ``run_id``.
        """
        from claude_task_master.mcp import tools

        raw = await anyio.to_thread.run_sync(partial(tools.plan_repo, work_dir, goal, model))
        return _classify_repo_result(raw)
