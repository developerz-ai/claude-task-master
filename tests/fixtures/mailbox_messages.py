"""Sample mailbox messages for testing.

This module provides test data for mailbox-related tests.
"""

from datetime import datetime

# Sample mailbox messages with various priorities and senders
SAMPLE_MESSAGES = [
    {
        "content": "Add rate limiting to the API endpoints",
        "sender": "developer1",
        "priority": 1,  # NORMAL
        "metadata": {"source": "cli"},
    },
    {
        "content": "URGENT: Fix security vulnerability in authentication",
        "sender": "security-team",
        "priority": 3,  # URGENT
        "metadata": {"source": "api", "ticket": "SEC-123"},
    },
    {
        "content": "Update documentation for new features",
        "sender": "tech-writer",
        "priority": 0,  # LOW
        "metadata": {"source": "mcp"},
    },
    {
        "content": "Add caching layer for performance improvement",
        "sender": "developer2",
        "priority": 2,  # HIGH
        "metadata": {"source": "cli"},
    },
]

# Messages for multi-instance coordination scenarios
MULTI_INSTANCE_MESSAGES = [
    {
        "content": "Instance 1 completed database migration",
        "sender": "instance-1",
        "priority": 1,
        "metadata": {"instance_id": "i-001", "task": "db_migration"},
    },
    {
        "content": "Instance 2 needs assistance with API integration",
        "sender": "instance-2",
        "priority": 2,
        "metadata": {"instance_id": "i-002", "task": "api_integration"},
    },
    {
        "content": "Instance 3 reporting test failures",
        "sender": "instance-3",
        "priority": 3,
        "metadata": {"instance_id": "i-003", "task": "testing"},
    },
]

# Messages with special content for edge case testing
EDGE_CASE_MESSAGES = [
    {
        "content": "",
        "sender": "empty-content",
        "priority": 1,
        "metadata": {},
    },
    {
        "content": 'Message with "quotes" and <special> & characters',
        "sender": "special-chars",
        "priority": 1,
        "metadata": {},
    },
    {
        "content": "Japanese: 日本語テスト, Emoji: 🚀🎉",
        "sender": "unicode-test",
        "priority": 1,
        "metadata": {},
    },
    {
        "content": "A" * 10000,  # Very long message
        "sender": "long-content",
        "priority": 1,
        "metadata": {},
    },
    {
        "content": "Message\nwith\nnewlines\tand\ttabs",
        "sender": "whitespace",
        "priority": 1,
        "metadata": {},
    },
]

# Sample merged message output
EXPECTED_MERGED_OUTPUT = """**Consolidated Change Requests (4 messages)**
*Processed at: {timestamp}*

### Request 1 [URGENT] (from security-team)

URGENT: Fix security vulnerability in authentication

---

### Request 2 [HIGH] (from developer2)

Add caching layer for performance improvement

---

### Request 3 (from developer1)

Add rate limiting to the API endpoints

---

### Request 4 [LOW] (from tech-writer)

Update documentation for new features

**Please address ALL 4 change requests above in the plan update.**
Prioritize URGENT requests first, then HIGH, then others.
If requests conflict, prefer higher-priority requests."""


def get_sample_mailbox_state():
    """Get a sample mailbox state dictionary for testing."""
    return {
        "messages": SAMPLE_MESSAGES,
        "last_checked": datetime.now().isoformat(),
        "total_messages_received": len(SAMPLE_MESSAGES),
    }


def get_empty_mailbox_state():
    """Get an empty mailbox state for testing."""
    return {
        "messages": [],
        "last_checked": None,
        "total_messages_received": 0,
    }


def get_large_mailbox_state(count: int = 100):
    """Get a mailbox state with many messages for performance testing."""
    messages = []
    for i in range(count):
        messages.append(
            {
                "content": f"Message {i}: Task to complete",
                "sender": f"sender-{i % 10}",
                "priority": i % 4,
                "metadata": {"index": i},
            }
        )
    return {
        "messages": messages,
        "last_checked": datetime.now().isoformat(),
        "total_messages_received": count,
    }
