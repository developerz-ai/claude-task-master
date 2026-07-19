"""Durable, cross-process control channel for stop/pause signals.

The orchestrator holds one long-lived in-memory ``TaskState`` and never
re-reads disk, while the REST (``claudetm-server``), MCP, and CLI control paths
call :class:`~claude_task_master.core.control.ControlManager` from *other*
processes. A process-local ``threading.Event`` (``request_shutdown``) is
invisible across that boundary, so ``POST /control/stop`` returned ``200`` while
a CLI-launched run kept going.

This module adds a tiny durable file, ``control.json``, in the state directory.
It carries a single ``control_requested`` field (``"stop"``, ``"pause"``, or
absent). :class:`~claude_task_master.core.control.ControlManager` writes it; the
orchestrator polls it once per loop cycle and honours it. Because the file is
durable and shared, the signal crosses the process boundary the ``Event`` never
could.

Writes go through :func:`~claude_task_master.core.atomic_io.atomic_write_json`
(temp-file + fsync + atomic rename), so a stop signal survives a crash. Reads
are tolerant of a missing, empty, or corrupt file — they report "no request"
rather than raising, so a partially-written or hand-deleted file can never wedge
the poll loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from claude_task_master.core.atomic_io import atomic_write_json

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["ControlAction", "ControlChannel", "ControlRequest", "CONTROL_FILE_NAME"]

ControlAction = Literal["stop", "pause"]

CONTROL_FILE_NAME = "control.json"

# Recognised actions. Anything else on disk is treated as "no request" so a
# stray/corrupt value cannot be interpreted as a stop.
_VALID_ACTIONS: frozenset[str] = frozenset({"stop", "pause"})


@dataclass(frozen=True)
class ControlRequest:
    """A pending cross-process control request.

    Attributes:
        action: The requested action, ``"stop"`` or ``"pause"``.
        reason: Optional human-readable reason recorded by the requester.
        requested_at: ISO-8601 timestamp string, or ``None`` if unrecorded.
    """

    action: ControlAction
    reason: str | None = None
    requested_at: str | None = None


class ControlChannel:
    """Durable file-backed control channel bound to a state directory.

    Reads and writes ``<state_dir>/control.json``. All reads are tolerant of a
    missing or corrupt file (they return ``None``), so the orchestrator poll and
    the shutdown bridge can never be crashed by a bad file.

    Attributes:
        state_dir: The task-master state directory holding ``control.json``.
    """

    def __init__(self, state_dir: Path):
        """Initialize the channel.

        Args:
            state_dir: State directory in which ``control.json`` lives.
        """
        self.state_dir = state_dir

    @property
    def path(self) -> Path:
        """Path to the backing ``control.json`` file."""
        return self.state_dir / CONTROL_FILE_NAME

    def request(self, action: ControlAction, reason: str | None = None) -> None:
        """Durably record a control request.

        Overwrites any prior request (last writer wins). The write is atomic and
        fsynced, so a crash leaves either the previous request or the new one —
        never a torn file.

        Args:
            action: ``"stop"`` or ``"pause"``.
            reason: Optional human-readable reason stored alongside the action.

        Raises:
            ValueError: If ``action`` is not a recognised control action.
            OSError: If the file cannot be written.
        """
        if action not in _VALID_ACTIONS:
            raise ValueError(f"Invalid control action: {action!r}")

        atomic_write_json(
            self.path,
            {
                "control_requested": action,
                "reason": reason,
                "requested_at": datetime.now().isoformat(),
            },
        )

    def read(self) -> ControlRequest | None:
        """Read the current control request, if any.

        Returns:
            A :class:`ControlRequest` when a valid ``stop``/``pause`` signal is
            pending, or ``None`` when the file is absent, empty, corrupt, or
            carries no recognised action.
        """
        path = self.path
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None

        action = data.get("control_requested")
        if action not in _VALID_ACTIONS:
            return None

        return ControlRequest(
            action=action,
            reason=data.get("reason"),
            requested_at=data.get("requested_at"),
        )

    def stop_requested(self) -> bool:
        """Return ``True`` iff a durable *stop* request is pending.

        Used as the durable bridge into
        :mod:`~claude_task_master.core.shutdown` so long in-cycle waits (e.g. CI
        polling via ``interruptible_sleep``) observe a cross-process stop.

        Returns:
            ``True`` if ``control.json`` currently requests ``"stop"``.
        """
        request = self.read()
        return request is not None and request.action == "stop"

    def clear(self) -> None:
        """Remove any pending control request.

        Called by the orchestrator once it has honoured a signal, and by
        ``resume`` before relaunching, so a stale ``stop``/``pause`` does not
        immediately re-trigger. Best-effort: a missing file is not an error.
        """
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return
