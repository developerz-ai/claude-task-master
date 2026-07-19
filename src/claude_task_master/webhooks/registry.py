"""Durable, lock-protected registry for webhook configurations.

Single source of truth for registered webhooks, consumed by BOTH the REST CRUD
routes (:mod:`claude_task_master.api.routes_webhooks`) AND the orchestrator's
fan-out emitter (:class:`claude_task_master.core.orchestrator.WebhookEmitter`).

Before this registry existed the two systems never met: the REST routes wrote a
``webhooks.json`` that nothing read, while the orchestrator delivered only to a
single ``--webhook-url`` client. Registered webhooks therefore never received
any events. The registry closes that gap — the routes persist through it and the
orchestrator reads from it to fan events out to every subscribed endpoint.

Storage mirrors the mailbox/state hardening so the file is safe under the
concurrent REST / MCP / CLI writers that all share it:

* every mutation runs its load → modify → save under an exclusive ``flock`` on
  ``.webhooks.lock`` (see :func:`claude_task_master.core.state.file_lock`), so
  two concurrent ``POST /webhooks`` calls cannot clobber each other and lose a
  registration;
* the write goes through the shared
  :func:`claude_task_master.core.atomic_io.atomic_write_json` (temp file + fsync
  + atomic rename + directory fsync), so a crash mid-save can never truncate
  ``webhooks.json`` and silently discard every registration on the next load.

On-disk format (unchanged, backward compatible with the previous inline
helpers)::

    {"webhooks": {webhook_id: {<record>}}, "updated_at": "<iso8601>"}

where each ``<record>`` is a :class:`~claude_task_master.webhooks.config.WebhookConfig`'s
fields plus ``created_at`` / ``updated_at`` bookkeeping timestamps.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from claude_task_master.core.atomic_io import atomic_write_json
from claude_task_master.core.state import file_lock
from claude_task_master.webhooks.config import WebhookConfig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

    from claude_task_master.webhooks.events import EventType

logger = logging.getLogger(__name__)

#: Name of the registry file inside the state directory.
WEBHOOKS_FILE = "webhooks.json"


# =============================================================================
# Exceptions
# =============================================================================


class WebhookRegistryError(Exception):
    """Base class for webhook registry errors."""


class WebhookNotFoundError(WebhookRegistryError):
    """Raised when a webhook id is not present in the registry.

    Attributes:
        webhook_id: The id that was not found.
    """

    def __init__(self, webhook_id: str) -> None:
        """Initialise the error.

        Args:
            webhook_id: The id that was looked up but not found.
        """
        self.webhook_id = webhook_id
        super().__init__(f"Webhook '{webhook_id}' not found")


class WebhookConflictError(WebhookRegistryError):
    """Raised when a webhook URL collides with an existing registration.

    Attributes:
        url: The conflicting URL.
        existing_id: The id of the webhook that already uses the URL.
    """

    def __init__(self, url: str, existing_id: str) -> None:
        """Initialise the error.

        Args:
            url: The URL that collided.
            existing_id: The id of the pre-existing webhook using the URL.
        """
        self.url = url
        self.existing_id = existing_id
        super().__init__(f"A webhook with URL '{url}' already exists (id: {existing_id})")


# =============================================================================
# Registry
# =============================================================================


class WebhookRegistry:
    """Durable, flock-protected store of webhook configurations.

    Bound to a single state directory. Reads are lock-free (the atomic write
    guarantees a reader always sees either the previous or the next complete
    file, never a torn one); mutations run under an exclusive file lock via
    :meth:`transaction` so concurrent writers serialise instead of overwriting.

    Attributes:
        state_dir: The task-master state directory holding ``webhooks.json``.
        storage_path: Full path to the backing ``webhooks.json`` file.
    """

    #: Seconds to wait for the registry lock before giving up. Matches
    #: ``StateManager.LOCK_TIMEOUT`` / ``MailboxStorage.LOCK_TIMEOUT`` so
    #: contention behaves consistently across the shared state directory.
    LOCK_TIMEOUT = 5.0

    def __init__(self, state_dir: Path | None = None) -> None:
        """Initialise the registry.

        Args:
            state_dir: Directory for state files. Defaults to
                ``.claude-task-master`` relative to the current directory.
        """
        self.state_dir = state_dir or Path(".claude-task-master")
        self.storage_path = self.state_dir / WEBHOOKS_FILE
        # Serialises concurrent mutations across processes/threads. Held only
        # around the load → modify → save critical section, never during reads.
        self._lock_file = self.state_dir / ".webhooks.lock"

    # -------------------------------------------------------------------------
    # Reads (lock-free)
    # -------------------------------------------------------------------------

    def load(self) -> dict[str, dict[str, Any]]:
        """Return all stored webhook records.

        Tolerant of a missing, empty, or corrupt file: any read/parse failure is
        logged and reported as an empty registry rather than raising, so a
        partially-written or hand-edited file can never wedge the routes or the
        emitter fan-out.

        Returns:
            Mapping of webhook id to its stored configuration record. Empty when
            the file is absent or unreadable.
        """
        if not self.storage_path.exists():
            return {}
        try:
            with open(self.storage_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Failed to load webhooks file %s: %s", self.storage_path, e)
            return {}

        if not isinstance(data, dict):
            return {}
        webhooks = data.get("webhooks", {})
        return webhooks if isinstance(webhooks, dict) else {}

    def get(self, webhook_id: str) -> dict[str, Any] | None:
        """Return a single webhook record by id.

        Args:
            webhook_id: The webhook id to look up.

        Returns:
            The stored record, or ``None`` if no such webhook exists.
        """
        return self.load().get(webhook_id)

    # -------------------------------------------------------------------------
    # Mutation primitive (locked, atomic)
    # -------------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[dict[str, dict[str, Any]]]:
        """Atomically read-modify-write the registry under an exclusive lock.

        Acquires the ``.webhooks.lock`` file lock, loads the current records,
        and yields the mutable mapping. On a clean exit the mapping is written
        back atomically and durably. If the ``with`` body raises, the write is
        skipped so a validation, conflict, or not-found error leaves the on-disk
        registry exactly as it was.

        Yields:
            The current webhook records, mutable in place by the caller.

        Raises:
            StateLockError: If the lock cannot be acquired within
                :data:`LOCK_TIMEOUT` seconds.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(self._lock_file, timeout=self.LOCK_TIMEOUT):
            webhooks = self.load()
            yield webhooks
            self._save(webhooks)

    def _save(self, webhooks: dict[str, dict[str, Any]]) -> None:
        """Persist the records mapping atomically and durably.

        Args:
            webhooks: The full records mapping to write.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.storage_path,
            {"webhooks": webhooks, "updated_at": datetime.now().isoformat()},
        )

    # -------------------------------------------------------------------------
    # Fan-out helper
    # -------------------------------------------------------------------------

    def configs_for_event(self, event_type: EventType | str) -> list[tuple[str, WebhookConfig]]:
        """Return the webhooks that should receive a given event.

        Builds a :class:`~claude_task_master.webhooks.config.WebhookConfig` from
        each stored record and keeps only those that are enabled and subscribed
        to ``event_type`` (per :meth:`WebhookConfig.should_send_event`). A record
        that fails to parse is skipped with a warning rather than aborting the
        whole fan-out.

        Args:
            event_type: The event being emitted (``EventType`` or its string
                value, e.g. ``"run.started"``).

        Returns:
            List of ``(webhook_id, config)`` pairs for the matching webhooks.
        """
        matches: list[tuple[str, WebhookConfig]] = []
        for webhook_id, record in self.load().items():
            try:
                config = self._record_to_config(record)
            except Exception as e:  # noqa: BLE001 - one bad record must not break fan-out
                logger.warning("Skipping invalid webhook %s: %s", webhook_id, e)
                continue
            if config.enabled and config.should_send_event(event_type):
                matches.append((webhook_id, config))
        return matches

    @staticmethod
    def _record_to_config(record: dict[str, Any]) -> WebhookConfig:
        """Build a validated ``WebhookConfig`` from a stored record.

        Only recognised model fields are passed through, so bookkeeping keys
        (``created_at`` / ``updated_at``) are dropped regardless of the model's
        extra-field policy.

        Args:
            record: A stored webhook record.

        Returns:
            The parsed and validated configuration.

        Raises:
            pydantic.ValidationError: If the record is not a valid webhook.
        """
        fields = {k: v for k, v in record.items() if k in WebhookConfig.model_fields}
        return WebhookConfig(**fields)
