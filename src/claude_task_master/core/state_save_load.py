"""Save, load, and migration methods for StateManager.

Mixin class :class:`_StateSaveLoadMixin` provides:

- :meth:`save_state` / :meth:`save_state_merged` / :meth:`_merge_control_fields`
- :meth:`load_state` / :meth:`_load_state_internal`
- :meth:`_migrate_state` (static)
- :meth:`_validate_transition` / :meth:`_atomic_write_json`
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from claude_task_master.core.atomic_io import atomic_write_json
from claude_task_master.core.state_exceptions import (
    CONTROL_AUTHORITATIVE_STATUSES,
    VALID_TRANSITIONS,
    InvalidStateTransitionError,
    StateCorruptedError,
    StateNotFoundError,
    StatePermissionError,
    StateValidationError,
)
from claude_task_master.core.state_models import (
    TaskState,
    file_lock,
)


class _StateSaveLoadMixin:
    """Mixin providing save/load/migrate/validate helpers for StateManager.

    The concrete :class:`StateManager` class supplies the instance attributes
    referenced here (``_lock_file``, ``LOCK_TIMEOUT``) and overrides
    :attr:`state_file` with a concrete property. Cross-mixin calls to
    :meth:`create_state_backup` and :meth:`_attempt_recovery` (from
    :class:`BackupRecoveryMixin`) are annotated with ``# type: ignore`` because
    mypy cannot verify them within the mixin alone; they resolve at runtime via
    MRO on the concrete class.
    """

    # Declared so mypy can type-check; supplied by StateManager.__init__ / class body.
    _lock_file: Path
    LOCK_TIMEOUT: float

    @property
    def state_file(self) -> Path:
        """Path to state.json — overridden by StateManager."""
        raise NotImplementedError  # pragma: no cover

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_state(
        self,
        state: TaskState,
        validate_transition: bool = True,
        merge_control: bool = False,
    ) -> TaskState:
        """Save state to state.json with file locking.

        The optional control-field merge, the transition check, the atomic
        write, and the rotating backup all run under a single exclusive lock.
        The current on-disk state is read *inside* the lock (not before acquiring
        it) so a concurrent writer in another process cannot change the on-disk
        status/options between the read and the write (time-of-check-to-
        time-of-use). ``_load_state_internal`` may heal a corrupt file via
        recovery, which is safe here because we hold the exclusive lock. On
        success a rotating backup of the written state is created (best-effort)
        so a later corruption can be recovered from the most recent good state.

        Args:
            state: The TaskState to save. Mutated in place: ``updated_at`` is
                refreshed, and when ``merge_control`` is set the control-plane
                fields (see :meth:`_merge_control_fields`) are overlaid.
            validate_transition: If True, validates state transition (default True).
            merge_control: If True, overlay control-plane-owned fields
                (``options`` and an externally-set ``stopped``/``paused`` status)
                from disk before writing — the reload-merge-save discipline used
                by the long-running orchestrator so it cannot clobber a signal
                written by another process. Default False. See
                :meth:`save_state_merged`.

        Returns:
            The state written to disk (the same object, with any merged fields
            applied), so a caller can adopt authoritative external changes.

        Raises:
            InvalidStateTransitionError: If the state transition is invalid.
            StatePermissionError: If the file cannot be written.
            StateLockError: If the file lock cannot be acquired.
        """
        state_file = self.state_file
        with file_lock(self._lock_file, timeout=self.LOCK_TIMEOUT):
            # Read the current on-disk state once, inside the lock, for both the
            # control-field merge and the transition check. Doing it here (not
            # before acquiring the lock) closes the time-of-check-to-time-of-use
            # gap: no other writer can change status/options between the read and
            # the write. _load_state_internal may heal a corrupt file via
            # recovery, which is safe here because we hold the exclusive lock.
            current_state: TaskState | None = None
            if (validate_transition or merge_control) and state_file.exists():
                try:
                    current_state = self._load_state_internal()
                except (StateNotFoundError, StateCorruptedError):
                    # If we can't load current state, fall back to a plain save.
                    current_state = None

            if merge_control and current_state is not None:
                self._merge_control_fields(current_state, state)

            if validate_transition and current_state is not None:
                self._validate_transition(current_state.status, state.status)

            state.updated_at = datetime.now().isoformat()

            try:
                # Use atomic write with temp file.
                # Use mode='json' to serialize datetime fields as ISO strings.
                self._atomic_write_json(state_file, state.model_dump(mode="json"))
            except PermissionError as e:
                raise StatePermissionError(state_file, "writing", e) from e

            # Keep a rotating backup of every durable write so a later
            # corruption can be recovered from the most recent good state.
            # Best-effort: a backup failure must never fail the save itself.
            self.create_state_backup()  # type: ignore[attr-defined]

        return state

    def save_state_merged(self, state: TaskState) -> TaskState:
        """Reload-merge-save: overlay externally-set control fields, then persist.

        Use this instead of :meth:`save_state` from the long-running
        orchestrator, which holds one in-memory :class:`TaskState` and saves it
        dozens of times per run. Between those saves another process — the REST
        server (``claudetm-server``), the MCP server, or a second CLI — may have
        written an authoritative control status or patched the run's options
        through :class:`~claude_task_master.core.control.ControlManager`. A plain
        :meth:`save_state` would overwrite those with the orchestrator's stale
        copy; this re-reads the on-disk state and merges the control-plane-owned
        fields *inside the same exclusive lock* as the write (no
        time-of-check-to-time-of-use gap), so:

        - a live ``PATCH /config`` (``update_options``) is preserved on disk and
          returned, so the running orchestrator adopts the new options; and
        - a cross-process ``stopped``/``paused`` is never overwritten by the
          orchestrator's stale copy (see :meth:`_merge_control_fields`).

        Args:
            state: The orchestrator's in-memory state to persist. Overlaid
                fields are applied **in place**, so the caller's own object picks
                up an external stop/pause and any patched options with no
                reassignment (the same object is threaded through the whole run).

        Returns:
            The same state object, with authoritative external fields overlaid,
            for callers that prefer to adopt it explicitly.

        Raises:
            InvalidStateTransitionError: If the resulting transition is invalid.
            StatePermissionError: If the file cannot be written.
            StateLockError: If the file lock cannot be acquired.
        """
        return self.save_state(state, merge_control=True)

    def _merge_control_fields(self, on_disk: TaskState, incoming: TaskState) -> None:
        """Overlay control-plane-owned fields from disk onto ``incoming`` in place.

        Called under the state lock by :meth:`save_state` when ``merge_control``
        is set. The orchestrator owns most of :class:`TaskState` (task index,
        session count, workflow stage, PR counters, …) and its in-memory value is
        authoritative for those. Two fields are instead owned by the *control
        plane* (:class:`~claude_task_master.core.control.ControlManager`, driven
        from the REST/MCP/CLI surfaces, possibly in another process) and must win
        over the orchestrator's stale copy:

        - **options** — always taken from disk. The orchestrator never changes
          its own options mid-run, so any on-disk difference is a live
          ``PATCH /config`` that must survive and be adopted.
        - **status** — a cross-process ``stopped``/``paused`` (one of
          :data:`CONTROL_AUTHORITATIVE_STATUSES`) is kept regardless of the
          incoming status. A routine progress save therefore cannot silently
          resume the run to ``working``, and even a terminal write
          (``blocked``/``success``/``failed``) that *raced* an external stop
          defers to the control signal — the run stays resumable rather than
          being finalized behind the user's back. Keeping the on-disk value also
          makes the persisted transition a no-op, so it never trips
          :meth:`_validate_transition` (``stopped`` -> ``blocked``, for example,
          is not otherwise a valid transition). Only an explicit ``resume`` —
          which uses plain :meth:`save_state`, not this path — moves off it.

        Args:
            on_disk: The freshly-loaded on-disk state, authoritative for the
                control-plane fields.
            incoming: The caller's state, mutated in place with the overlay.
        """
        # External config (update_options / PATCH /config) always wins; copy so
        # the caller does not alias the soon-discarded on-disk object.
        incoming.options = on_disk.options.model_copy(deep=True)

        # An externally-set stop/pause is authoritative: keep it. Only a
        # deliberate resume (plain save_state) may move a run off stopped/paused.
        if on_disk.status in CONTROL_AUTHORITATIVE_STATUSES:
            incoming.status = on_disk.status

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_state(self) -> TaskState:
        """Load state from state.json with error recovery.

        Acquires the *exclusive* lock rather than a shared one: on a corrupt
        state file :meth:`_load_state_internal` triggers recovery, which heals
        ``state.json`` by writing the newest good backup back to disk. Writing
        under a shared lock would let two concurrent readers recover-and-write at
        the same time; the exclusive lock serializes them. The state file is
        tiny, so serializing reads costs nothing measurable.

        Returns:
            TaskState: The loaded task state.

        Raises:
            StateNotFoundError: If the state file does not exist.
            StateCorruptedError: If the state file is corrupted and cannot be recovered.
            StateValidationError: If the state data fails validation.
            StatePermissionError: If the file cannot be read.
            StateLockError: If the file lock cannot be acquired.
        """
        with file_lock(self._lock_file, timeout=self.LOCK_TIMEOUT):
            return self._load_state_internal()

    def _load_state_internal(self) -> TaskState:
        """Load and parse state without acquiring the lock.

        The caller MUST already hold the exclusive state lock: on corruption
        this delegates to :meth:`_attempt_recovery`, which writes the healed
        state back to ``state.json``. Both callers (:meth:`load_state` and
        :meth:`save_state`) invoke it inside ``file_lock``.
        """
        state_file = self.state_file
        if not state_file.exists():
            raise StateNotFoundError(state_file)

        try:
            with open(state_file) as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    # Attempt recovery from backup
                    recovered_state: TaskState | None = self._attempt_recovery(e)  # type: ignore[attr-defined]
                    if recovered_state:
                        return recovered_state
                    raise StateCorruptedError(
                        state_file,
                        f"JSON parse error at line {e.lineno}, column {e.colno}: {e.msg}",
                        recoverable=False,
                    ) from e
        except PermissionError as e:
            raise StatePermissionError(state_file, "reading", e) from e

        # Handle empty JSON
        if not data:
            recovered_state_empty: TaskState | None = self._attempt_recovery(  # type: ignore[attr-defined]
                ValueError("Empty JSON object")
            )
            if recovered_state_empty:
                return recovered_state_empty
            raise StateCorruptedError(
                state_file,
                "State file is empty or contains an empty JSON object",
                recoverable=False,
            )

        # A valid state file is a JSON object. A bare list, number, or string is
        # corruption: route it through the same backup-recovery path as a parse
        # error rather than letting the ``TaskState(**data)`` below raise an
        # uncaught TypeError that bypasses both recovery and StateValidationError.
        if not isinstance(data, dict):
            recovered_non_dict: TaskState | None = self._attempt_recovery(  # type: ignore[attr-defined]
                TypeError(f"State root is a JSON {type(data).__name__}, expected an object")
            )
            if recovered_non_dict:
                return recovered_non_dict
            raise StateCorruptedError(
                state_file,
                f"State root is a JSON {type(data).__name__}, expected an object",
                recoverable=False,
            )

        # Migrate the raw dict to the current schema version before pydantic
        # validation. Older state is upgraded in place; state from a newer
        # version is rejected here rather than having its unknown fields
        # silently dropped and then destroyed on the next save.
        data = self._migrate_state(data)

        # Validate and parse the state data
        try:
            return TaskState(**data)
        except ValidationError as e:
            # Extract meaningful error messages
            missing_fields = []
            invalid_fields = []
            for error in e.errors():
                field = ".".join(str(loc) for loc in error["loc"])
                if error["type"] == "missing":
                    missing_fields.append(field)
                else:
                    invalid_fields.append(f"{field}: {error['msg']}")

            raise StateValidationError(
                "State file has invalid structure",
                missing_fields=missing_fields if missing_fields else None,
                invalid_fields=invalid_fields if invalid_fields else None,
            ) from e

    @staticmethod
    def _migrate_state(data: dict[str, Any]) -> dict[str, Any]:
        """Migrate a raw state dict to the current schema version.

        Applies the steps in :data:`_STATE_MIGRATIONS` in sequence from the
        on-disk ``schema_version`` up to :data:`CURRENT_SCHEMA_VERSION`, then
        stamps the current version onto the result. State written before schema
        versioning existed (no ``schema_version`` key) is treated as version 1 —
        the initial schema. A *present* but malformed marker is rejected rather
        than assumed to be version 1.

        Rejecting state written by a *newer* version is deliberate: pydantic
        would otherwise silently drop the unknown fields and then destroy them
        on the next save, so a forward-incompatible resume must fail loudly.

        Args:
            data: The raw state dict parsed from ``state.json``.

        Returns:
            The migrated state dict, tagged with the current schema version.

        Raises:
            StateValidationError: If the state was written by a newer schema
                version, or no migration path exists from the on-disk version.
        """
        # Deferred import so tests can patch state.CURRENT_SCHEMA_VERSION and
        # state._STATE_MIGRATIONS via monkeypatch.setattr(state_module, ...).
        import claude_task_master.core.state as _state  # noqa: PLC0415

        _CURRENT_SCHEMA_VERSION = _state.CURRENT_SCHEMA_VERSION
        _migrations = _state._STATE_MIGRATIONS

        # Non-mapping JSON (a bare list/number/string) is left untouched so the
        # downstream ``TaskState(**data)`` surfaces the corruption as it would
        # without migration, instead of an AttributeError on ``.get`` here.
        if not isinstance(data, dict):
            return data

        # Only an *absent* marker proves legacy version 1 — the field simply did
        # not exist before schema versioning. A *present* but malformed marker
        # ("abc", 0, a float, or a bool) is corruption: treating it as version 1
        # could apply the wrong migrations and silently discard forward-schema
        # fields, so reject it loudly instead.
        if "schema_version" not in data:
            version = 1
        else:
            raw_version = data["schema_version"]
            if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 1:
                raise StateValidationError(
                    "State file has an invalid schema version",
                    invalid_fields=["schema_version: expected a positive integer"],
                )
            version = raw_version

        if version > _CURRENT_SCHEMA_VERSION:
            raise StateValidationError(
                f"State schema version {version} is newer than the supported "
                f"version {_CURRENT_SCHEMA_VERSION}",
                invalid_fields=[
                    "schema_version: written by a newer claude-task-master; "
                    "upgrade it or run 'clean' to start fresh"
                ],
            )

        while version < _CURRENT_SCHEMA_VERSION:
            migrate = _migrations.get(version)
            if migrate is None:
                raise StateValidationError(
                    f"No migration path from state schema version {version} to "
                    f"{_CURRENT_SCHEMA_VERSION}",
                    invalid_fields=["schema_version: unmigratable state"],
                )
            data = migrate(data)
            version += 1

        data["schema_version"] = _CURRENT_SCHEMA_VERSION
        return data

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_transition(self, current_status: str, new_status: str) -> None:
        """Validate that a state transition is allowed.

        Args:
            current_status: The current status value.
            new_status: The new status value.

        Raises:
            InvalidStateTransitionError: If the transition is not allowed.
        """
        # Same status is always allowed (no actual transition)
        if current_status == new_status:
            return

        valid_next_states = VALID_TRANSITIONS.get(current_status, frozenset())
        if new_status not in valid_next_states:
            raise InvalidStateTransitionError(current_status, new_status)

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        """Atomically and durably write JSON data to a file.

        Delegates to the shared :func:`atomic_write_json` helper, which writes
        to a temp file, fsyncs it, renames it over the target, then fsyncs the
        parent directory so a crash cannot leave a truncated ``state.json``.

        Args:
            path: The target file path.
            data: The data to write as JSON.
        """
        atomic_write_json(path, data)


__all__ = ["_StateSaveLoadMixin"]
