"""Forwarding-tool specifications and response-model re-exports for the MCP server.

The :data:`_FORWARDING_SPECS` table drives :func:`register_forwarding_tools`:
each entry pairs a ``tools`` function with a client-facing description so that
parameter lists are always derived from the underlying function signature —
nothing can silently drift or be dropped from a hand-written wrapper.

Response model re-exports let callers import from this module or from
:mod:`server` interchangeably.
"""

from __future__ import annotations

from claude_task_master.mcp import tools
from claude_task_master.mcp.tool_forwarding import ForwardingSpec

# =============================================================================
# Re-export response models for convenience
# =============================================================================

TaskStatus = tools.TaskStatus
StartTaskResult = tools.StartTaskResult
CleanResult = tools.CleanResult
LogsResult = tools.LogsResult
HealthCheckResult = tools.HealthCheckResult
PauseTaskResult = tools.PauseTaskResult
StopTaskResult = tools.StopTaskResult
ResumeTaskResult = tools.ResumeTaskResult
UpdateConfigResult = tools.UpdateConfigResult
SendMessageResult = tools.SendMessageResult
MailboxStatusResult = tools.MailboxStatusResult
ClearMailboxResult = tools.ClearMailboxResult
CloneRepoResult = tools.CloneRepoResult
SetupRepoResult = tools.SetupRepoResult
PlanRepoResult = tools.PlanRepoResult
DeleteCodingStyleResult = tools.DeleteCodingStyleResult


# =============================================================================
# Forwarding tool table
# =============================================================================
#
# The task and mailbox tools all inject ``work_dir`` and forward to a matching
# ``tools`` function. Declaring them here -- rather than hand-writing one
# ``@mcp.tool()`` wrapper each -- means every tool's parameters are DERIVED from
# the underlying function (see ``register_forwarding_tools``), so a parameter can
# never be silently dropped from a wrapper again (as ``enable_verification`` was
# from ``initialize_task``). Only the client-facing description lives here.
_FORWARDING_SPECS: tuple[ForwardingSpec, ...] = (
    ForwardingSpec(
        tools.get_status,
        "Get the current status of a claudetm task.\n\n"
        "Returns task goal, status, model, current task index, session count,\n"
        "and configuration options.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary containing task status information.",
    ),
    ForwardingSpec(
        tools.get_plan,
        "Get the current task plan with checkboxes.\n\n"
        "Returns the markdown task list showing completion status.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary containing the plan content or error.",
    ),
    ForwardingSpec(
        tools.get_logs,
        "Get logs from the current task run.\n\n"
        "Args:\n"
        "    tail: Number of lines to return from the end of the log.\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary containing log content or error.",
    ),
    ForwardingSpec(
        tools.get_progress,
        "Get the human-readable progress summary.\n\n"
        "Returns what has been accomplished and what remains.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary containing progress content or error.",
    ),
    ForwardingSpec(
        tools.get_context,
        "Get the accumulated context and learnings.\n\n"
        "Returns insights gathered during execution.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary containing context content or error.",
    ),
    ForwardingSpec(
        tools.clean_task,
        "Clean up task state directory.\n\n"
        "Removes all state files to allow starting fresh.\n\n"
        "Args:\n"
        "    force: If True, skip confirmation (always True for MCP).\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary indicating success or failure.",
    ),
    ForwardingSpec(
        tools.delete_coding_style,
        "Delete the coding style guide file (coding-style.md).\n\n"
        "The coding style file is a cached guide that's preserved across runs to\n"
        "save tokens. Call this to force regeneration on the next planning phase\n"
        "when project conventions have changed.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary indicating success or failure with deletion status.",
    ),
    ForwardingSpec(
        tools.initialize_task,
        "Initialize a new task with the given goal.\n\n"
        "This only initializes the task state - it does NOT run the task.\n"
        "Use this to set up a task that will be executed separately.\n\n"
        "Args:\n"
        "    goal: The goal to achieve.\n"
        "    model: Model to use (opus, sonnet, fable, haiku, sonnet_1m).\n"
        "    auto_merge: Whether to auto-merge PRs when approved.\n"
        "    enable_release: Whether to run post-merge release verification.\n"
        "    enable_verification: Run final success-criteria verification after\n"
        "        all tasks complete.\n"
        "    max_sessions: Max work sessions before pausing.\n"
        "    max_prs: Max pull requests to create.\n"
        "    pause_on_pr: Pause after creating PR for manual review.\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary indicating success with run_id or failure.",
    ),
    ForwardingSpec(
        tools.list_tasks,
        "List tasks from the current plan.\n\n"
        "Returns parsed tasks with their completion status.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary containing list of tasks with status.",
    ),
    ForwardingSpec(
        tools.pause_task,
        "Pause a running task.\n\n"
        "Transitions the task from planning/working status to paused status.\n"
        "The task can be resumed later using resume_task.\n\n"
        "Args:\n"
        "    reason: Optional reason for pausing (stored in progress).\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary indicating success or failure with status details.",
    ),
    ForwardingSpec(
        tools.stop_task,
        "Stop a running task and trigger graceful shutdown.\n\n"
        "Transitions the task from any active status to stopped status and\n"
        "triggers shutdown of any running processes. The task can be resumed\n"
        "later if not cleaned up.\n\n"
        "Args:\n"
        "    reason: Optional reason for stopping (stored in progress).\n"
        "    cleanup: If True, also cleanup state files after stopping.\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary indicating success or failure with status details.",
    ),
    ForwardingSpec(
        tools.resume_task,
        "Resume a paused or blocked task.\n\n"
        "Transitions the task from paused/blocked/stopped status back to working\n"
        "status. This is distinct from CLI resume - it only updates the state\n"
        "without restarting the work loop.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary indicating success or failure with status details.",
    ),
    ForwardingSpec(
        tools.update_config,
        "Update task configuration options at runtime.\n\n"
        "Updates the TaskOptions stored in the task state. Only specified\n"
        "options are updated; others retain their current values.\n\n"
        "Args:\n"
        "    auto_merge: Whether to auto-merge PRs when approved.\n"
        "    max_sessions: Maximum number of work sessions before pausing.\n"
        "    max_prs: Maximum number of pull requests to create.\n"
        "    pause_on_pr: Whether to pause after creating PR for manual review.\n"
        "    enable_checkpointing: Whether to enable state checkpointing.\n"
        "    log_level: Log level (quiet, normal, verbose).\n"
        "    log_format: Log format (text, json).\n"
        "    pr_per_task: Whether to create PR per task vs per group.\n"
        "    enable_release: Whether to run post-merge release verification.\n"
        "    enable_verification: Whether to run final success-criteria verification.\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary indicating success or failure with updated config.",
    ),
    ForwardingSpec(
        tools.send_message,
        "Send a message to the claudetm mailbox.\n\n"
        "Messages are processed after the current task completes. Multiple\n"
        "messages are merged into a single change request that updates the plan\n"
        "before continuing work.\n\n"
        "Use this to send instructions, feedback, or change requests to a running\n"
        "claudetm instance from external systems or other AI agents.\n\n"
        "Args:\n"
        "    content: The message content describing the change request.\n"
        '    sender: Identifier of the sender (default: "anonymous").\n'
        "    priority: Message priority - 0=low, 1=normal, 2=high, 3=urgent.\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary containing the message_id on success, or error info.",
    ),
    ForwardingSpec(
        tools.check_mailbox,
        "Check the status of the claudetm mailbox.\n\n"
        "Returns the number of pending messages and previews of each.\n"
        "Use this to see what messages are waiting to be processed.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary containing mailbox status with message previews.",
    ),
    ForwardingSpec(
        tools.clear_mailbox,
        "Clear all messages from the claudetm mailbox.\n\n"
        "Use this to discard all pending messages without processing them.\n\n"
        "Args:\n"
        "    state_dir: Optional custom state directory path.\n\n"
        "Returns:\n"
        "    Dictionary indicating success and number of messages cleared.",
    ),
)

__all__ = [
    "_FORWARDING_SPECS",
    "TaskStatus",
    "StartTaskResult",
    "CleanResult",
    "LogsResult",
    "HealthCheckResult",
    "PauseTaskResult",
    "StopTaskResult",
    "ResumeTaskResult",
    "UpdateConfigResult",
    "SendMessageResult",
    "MailboxStatusResult",
    "ClearMailboxResult",
    "CloneRepoResult",
    "SetupRepoResult",
    "PlanRepoResult",
    "DeleteCodingStyleResult",
]
