"""MailboxProcessor — mailbox checking and plan-update logic.

Extracted from WorkLoopOrchestrator._check_and_process_mailbox so the
class can be tested in isolation and kept under the 500-LOC file limit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from . import console
from .plan_parsing import count_completed_tasks, parse_task_descriptions

if TYPE_CHECKING:
    from ..mailbox import MailboxStorage, MessageMerger
    from .plan_updater import PlanUpdater
    from .state import StateManager, TaskState
    from .webhook_emitter import WebhookEmitter

logger = logging.getLogger(__name__)


class MailboxProcessor:
    """Checks the mailbox and updates the plan when messages are present.

    Called after each task completion by the orchestrator loop. Merges
    pending messages and delegates to ``PlanUpdater`` to apply the change
    request to the current plan. Emits a ``plan.updated`` webhook event on
    every successful check (with or without plan changes).

    Attributes:
        _mailbox_storage: Persistent storage for mailbox messages.
        _message_merger: Merges multiple messages into a single change request.
        _plan_updater: Applies the merged request to the plan file.
        _webhook_emitter: Emits ``plan.updated`` webhook events.
        _state_manager: Loads the plan and persists state timestamps.
    """

    def __init__(
        self,
        mailbox_storage: MailboxStorage,
        message_merger: MessageMerger,
        plan_updater: PlanUpdater,
        webhook_emitter: WebhookEmitter,
        state_manager: StateManager,
    ) -> None:
        self._mailbox_storage = mailbox_storage
        self._message_merger = message_merger
        self._plan_updater = plan_updater
        self._webhook_emitter = webhook_emitter
        self._state_manager = state_manager

    # ------------------------------------------------------------------
    # Internal task-count helpers
    # ------------------------------------------------------------------

    def _get_total_tasks(self, state: TaskState) -> int:
        """Return the total number of tasks in the current plan.

        Args:
            state: Current task state (unused; kept for symmetry with
                ``_get_completed_tasks``).

        Returns:
            Total task count, or 0 if the plan cannot be loaded.
        """
        try:
            plan = self._state_manager.load_plan()
            if plan:
                tasks = parse_task_descriptions(plan)
                return len(tasks)
        except Exception:
            pass
        return 0

    def _get_completed_tasks(self, state: TaskState) -> int:
        """Return the number of completed tasks in the current plan.

        Counts ``- [x]``/``- [X]`` check-boxes via :func:`count_completed_tasks`.

        Args:
            state: Current task state — used as fallback when the plan
                cannot be loaded.

        Returns:
            Completed task count, or ``state.current_task_index`` on error.
        """
        try:
            plan = self._state_manager.load_plan()
            if plan:
                return count_completed_tasks(plan)
        except Exception:
            pass
        return state.current_task_index

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def check_and_process(self, state: TaskState) -> bool:
        """Check the mailbox and update the plan when messages are present.

        The last_mailbox_check timestamp is always updated regardless of
        whether messages were found, to track when the mailbox was last
        monitored.

        Messages are peeked (not removed) before processing. They are only
        removed after a successful plan update so a transient failure
        (network, API, etc.) does not permanently lose the user's change
        requests.

        Args:
            state: Current task state. ``last_mailbox_check`` and
                ``current_task_index`` may be mutated and persisted.

        Returns:
            True if the plan was updated, False otherwise.
        """
        logger.debug(
            "Mailbox check starting: task_index=%d, session_count=%d",
            state.current_task_index,
            state.session_count,
        )

        # Fast path: no messages.
        message_count = self._mailbox_storage.count()
        if message_count == 0:
            check_time = datetime.now()
            logger.debug(
                "Mailbox check complete: no messages, timestamp=%s",
                check_time.isoformat(),
            )
            state.last_mailbox_check = check_time
            self._state_manager.save_state_merged(state)
            return False

        logger.info("Mailbox check: found %d message(s) to process", message_count)
        console.info(f"Found {message_count} message(s) in mailbox - processing...")

        # Peek messages WITHOUT removing them; removal happens only after the
        # plan update succeeds so failures are retried on the next check.
        messages = self._mailbox_storage.get_messages()
        if not messages:
            # Race condition — cleared by another process between count and get.
            logger.warning(
                "Mailbox race condition: messages disappeared between count (%d) and get",
                message_count,
            )
            return False

        for msg in messages:
            logger.info(
                "Mailbox message: id=%s, sender=%s, priority=%s, timestamp=%s, content_length=%d",
                msg.id,
                msg.sender,
                msg.priority.name if hasattr(msg.priority, "name") else msg.priority,
                msg.timestamp.isoformat() if msg.timestamp else "none",
                len(msg.content),
            )

        logger.debug(
            "Merging %d mailbox messages from senders: %s",
            len(messages),
            [msg.sender for msg in messages],
        )
        try:
            merged_content = self._message_merger.merge(messages)
            logger.info(
                "Mailbox messages merged successfully: total_length=%d, preview=%s...",
                len(merged_content),
                merged_content[:100].replace("\n", " "),
            )
        except ValueError as e:
            logger.error(
                "Failed to merge mailbox messages: error=%s, message_count=%d",
                e,
                len(messages),
            )
            console.warning(f"Failed to merge mailbox messages: {e}")
            return False

        logger.debug("Starting plan update from mailbox messages")
        try:
            total_tasks_before = self._get_total_tasks(state)

            console.info("Updating plan based on mailbox messages...")
            result = self._plan_updater.update_plan(
                merged_content, current_task_index=state.current_task_index
            )

            # Adopt any positional-index reconciliation before the state save
            # below. current_task_index is orchestrator-owned (not merged from
            # disk by save_state_merged), so the stale in-memory value would
            # otherwise clobber the plan updater's on-disk fix.
            reconciled_index = result.get("current_task_index")
            if reconciled_index is not None:
                state.current_task_index = reconciled_index

            # Plan update succeeded — remove exactly the peeked message IDs so
            # any message that arrived during the update is kept for next check.
            logger.info("Dropping %d processed mailbox message(s)", len(messages))
            removed = self._mailbox_storage.remove_messages([msg.id for msg in messages])
            logger.debug(
                "Removed %d processed message(s) from mailbox after plan update",
                removed,
            )

            check_time = datetime.now()
            if result.get("changes_made"):
                console.success("Plan updated based on mailbox messages")
                logger.info(
                    "Plan updated from mailbox: changes_made=True, "
                    "message_count=%d, senders=%s, timestamp=%s",
                    len(messages),
                    [msg.sender for msg in messages],
                    check_time.isoformat(),
                )

                state.last_mailbox_check = check_time
                self._state_manager.save_state_merged(state)
                logger.debug(
                    "State saved with mailbox check timestamp: %s",
                    check_time.isoformat(),
                )

                updated_total_tasks = self._get_total_tasks(state)
                updated_completed_tasks = self._get_completed_tasks(state)
                task_diff = updated_total_tasks - total_tasks_before
                tasks_added = max(0, task_diff)
                tasks_removed = max(0, -task_diff)

                self._webhook_emitter.emit(
                    "plan.updated",
                    update_source="mailbox",
                    message=merged_content[:500] if merged_content else None,
                    total_tasks=updated_total_tasks,
                    completed_tasks=updated_completed_tasks,
                    tasks_added=tasks_added,
                    tasks_modified=None,
                    tasks_removed=tasks_removed,
                )

                return True

            else:
                console.info("Mailbox messages processed - no plan changes needed")
                logger.info(
                    "Plan not modified from mailbox: message_count=%d, senders=%s, timestamp=%s",
                    len(messages),
                    [msg.sender for msg in messages],
                    check_time.isoformat(),
                )

                state.last_mailbox_check = check_time
                self._state_manager.save_state_merged(state)
                logger.debug(
                    "State saved with mailbox check timestamp: %s",
                    check_time.isoformat(),
                )

                current_total_tasks = self._get_total_tasks(state)
                current_completed_tasks = self._get_completed_tasks(state)

                self._webhook_emitter.emit(
                    "plan.updated",
                    update_source="mailbox",
                    message=merged_content[:500] if merged_content else None,
                    total_tasks=current_total_tasks,
                    completed_tasks=current_completed_tasks,
                    tasks_added=0,
                    tasks_modified=0,
                    tasks_removed=0,
                )

                return False

        except ValueError as e:
            # No plan exists — can't update.
            logger.error(
                "Cannot update plan from mailbox: no plan exists, error=%s, message_count=%d",
                e,
                len(messages),
            )
            console.warning(f"Cannot update plan: {e}")
            return False
        except Exception as e:
            logger.error(
                "Error updating plan from mailbox: error=%s, type=%s, message_count=%d",
                e,
                type(e).__name__,
                len(messages),
            )
            console.warning(f"Error updating plan from mailbox: {e}")
            return False
