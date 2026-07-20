"""Mailbox tool handlers for MCP.

Covers: send_message, check_mailbox, clear_mailbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_task_master.mcp.tool_models import (
    ClearMailboxResult,
    MailboxStatusResult,
    SendMessageResult,
)


def send_message(
    work_dir: Path,
    content: str,
    sender: str = "anonymous",
    priority: int = 1,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Send a message to the claudetm mailbox.

    Messages in the mailbox will be processed after the current task completes.
    Multiple messages are merged into a single change request that updates
    the plan before continuing work.

    Args:
        work_dir: Working directory for the server.
        content: The message content describing the change request.
        sender: Identifier of the sender (default: "anonymous").
        priority: Message priority (0=low, 1=normal, 2=high, 3=urgent).
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing the message_id on success, or error info.
    """
    from claude_task_master.mailbox import MailboxStorage

    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"

    # Validate content
    if not content or not content.strip():
        return SendMessageResult(
            success=False,
            error="Message content cannot be empty",
        ).model_dump()

    # Validate priority range
    if priority < 0 or priority > 3:
        return SendMessageResult(
            success=False,
            error="Priority must be between 0 (low) and 3 (urgent)",
        ).model_dump()

    try:
        mailbox = MailboxStorage(state_dir=state_path)
        message_id = mailbox.add_message(
            content=content.strip(),
            sender=sender,
            priority=priority,
        )

        return SendMessageResult(
            success=True,
            message_id=message_id,
            message=f"Message sent successfully (id: {message_id})",
        ).model_dump()
    except Exception as e:
        return SendMessageResult(
            success=False,
            error=f"Failed to send message: {e}",
        ).model_dump()


def check_mailbox(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Check the status of the claudetm mailbox.

    Returns the number of pending messages and previews of each.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing mailbox status information.
    """
    from claude_task_master.mailbox import MailboxStorage

    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"

    try:
        mailbox = MailboxStorage(state_dir=state_path)
        status = mailbox.get_status()

        return MailboxStatusResult(
            success=True,
            count=status["count"],
            previews=status["previews"],
            last_checked=status["last_checked"],
            total_messages_received=status["total_messages_received"],
        ).model_dump()
    except Exception as e:
        return MailboxStatusResult(
            success=False,
            error=f"Failed to check mailbox: {e}",
        ).model_dump()


def clear_mailbox(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Clear all messages from the claudetm mailbox.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success and number of messages cleared.
    """
    from claude_task_master.mailbox import MailboxStorage

    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"

    try:
        mailbox = MailboxStorage(state_dir=state_path)
        count = mailbox.clear()

        return ClearMailboxResult(
            success=True,
            messages_cleared=count,
            message=f"Cleared {count} message(s) from mailbox",
        ).model_dump()
    except Exception as e:
        return ClearMailboxResult(
            success=False,
            error=f"Failed to clear mailbox: {e}",
        ).model_dump()
