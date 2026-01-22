"""Tests for mailbox REST endpoints: POST /mailbox/send, GET /mailbox, DELETE /mailbox.

Tests the mailbox endpoints that allow external systems to send messages
to the claudetm mailbox for processing after tasks complete.
"""

import json
from datetime import datetime

# =============================================================================
# POST /mailbox/send Tests
# =============================================================================


def test_post_mailbox_send_success(api_client, temp_dir):
    """Test successful message send via POST /mailbox/send."""
    response = api_client.post(
        "/mailbox/send",
        json={
            "content": "Please also add tests for the new feature",
            "sender": "supervisor-agent",
            "priority": 2,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message_id"] is not None
    assert "sent successfully" in data["message"]

    # Verify message was persisted
    mailbox_file = temp_dir / ".claude-task-master" / "mailbox.json"
    assert mailbox_file.exists()
    mailbox_data = json.loads(mailbox_file.read_text())
    assert len(mailbox_data["messages"]) == 1
    assert mailbox_data["messages"][0]["content"] == "Please also add tests for the new feature"
    assert mailbox_data["messages"][0]["sender"] == "supervisor-agent"
    assert mailbox_data["messages"][0]["priority"] == 2


def test_post_mailbox_send_minimal_request(api_client, temp_dir):
    """Test message send with minimal required fields."""
    response = api_client.post(
        "/mailbox/send",
        json={"content": "Simple message"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message_id"] is not None

    # Verify defaults were applied
    mailbox_file = temp_dir / ".claude-task-master" / "mailbox.json"
    mailbox_data = json.loads(mailbox_file.read_text())
    assert mailbox_data["messages"][0]["sender"] == "anonymous"
    assert mailbox_data["messages"][0]["priority"] == 1  # NORMAL priority


def test_post_mailbox_send_with_metadata(api_client, temp_dir):
    """Test message send with optional metadata."""
    response = api_client.post(
        "/mailbox/send",
        json={
            "content": "Message with metadata",
            "sender": "test-system",
            "priority": 3,
            "metadata": {"source": "monitoring", "ticket_id": "TICKET-123"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Verify metadata was persisted
    mailbox_file = temp_dir / ".claude-task-master" / "mailbox.json"
    mailbox_data = json.loads(mailbox_file.read_text())
    assert mailbox_data["messages"][0]["metadata"]["source"] == "monitoring"
    assert mailbox_data["messages"][0]["metadata"]["ticket_id"] == "TICKET-123"


def test_post_mailbox_send_empty_content(api_client):
    """Test that empty content returns 400."""
    response = api_client.post(
        "/mailbox/send",
        json={"content": ""},
    )

    assert response.status_code == 422  # Pydantic validation error (min_length=1)


def test_post_mailbox_send_whitespace_only_content(api_client):
    """Test that whitespace-only content returns 400."""
    response = api_client.post(
        "/mailbox/send",
        json={"content": "   \n\t  "},
    )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "invalid_request"
    assert "empty or whitespace" in data["message"]


def test_post_mailbox_send_invalid_priority(api_client):
    """Test that invalid priority returns 422."""
    # Priority too high
    response = api_client.post(
        "/mailbox/send",
        json={"content": "Test", "priority": 5},
    )
    assert response.status_code == 422  # Pydantic validation error

    # Priority too low
    response = api_client.post(
        "/mailbox/send",
        json={"content": "Test", "priority": -1},
    )
    assert response.status_code == 422  # Pydantic validation error


def test_post_mailbox_send_all_priorities(api_client, temp_dir):
    """Test sending messages with all valid priority levels."""
    priorities = [0, 1, 2, 3]  # LOW, NORMAL, HIGH, URGENT

    for priority in priorities:
        response = api_client.post(
            "/mailbox/send",
            json={"content": f"Priority {priority} message", "priority": priority},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    # Verify all messages were stored
    mailbox_file = temp_dir / ".claude-task-master" / "mailbox.json"
    mailbox_data = json.loads(mailbox_file.read_text())
    assert len(mailbox_data["messages"]) == 4


def test_post_mailbox_send_multiple_messages(api_client, temp_dir):
    """Test sending multiple messages accumulates them."""
    messages = [
        {"content": "First message", "sender": "agent-1"},
        {"content": "Second message", "sender": "agent-2"},
        {"content": "Third message", "sender": "agent-3"},
    ]

    message_ids = []
    for msg in messages:
        response = api_client.post("/mailbox/send", json=msg)
        assert response.status_code == 200
        message_ids.append(response.json()["message_id"])

    # Verify all messages have unique IDs
    assert len(set(message_ids)) == 3

    # Verify all messages were stored
    mailbox_file = temp_dir / ".claude-task-master" / "mailbox.json"
    mailbox_data = json.loads(mailbox_file.read_text())
    assert len(mailbox_data["messages"]) == 3
    assert mailbox_data["total_messages_received"] == 3


def test_post_mailbox_send_long_content(api_client, temp_dir):
    """Test sending a message with long content."""
    long_content = "A" * 50000  # 50KB content

    response = api_client.post(
        "/mailbox/send",
        json={"content": long_content},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_post_mailbox_send_content_trimmed(api_client, temp_dir):
    """Test that content whitespace is trimmed."""
    response = api_client.post(
        "/mailbox/send",
        json={"content": "  message with spaces  \n"},
    )

    assert response.status_code == 200

    # Verify content was trimmed
    mailbox_file = temp_dir / ".claude-task-master" / "mailbox.json"
    mailbox_data = json.loads(mailbox_file.read_text())
    assert mailbox_data["messages"][0]["content"] == "message with spaces"


# =============================================================================
# GET /mailbox Tests
# =============================================================================


def test_get_mailbox_empty(api_client, temp_dir):
    """Test GET /mailbox when mailbox is empty."""
    response = api_client.get("/mailbox")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 0
    assert data["messages"] == []
    assert data["total_messages_received"] == 0


def test_get_mailbox_with_messages(api_client, temp_dir):
    """Test GET /mailbox when messages exist."""
    # First send some messages
    messages = [
        {"content": "First message", "sender": "agent-1", "priority": 1},
        {"content": "Second message", "sender": "agent-2", "priority": 2},
    ]
    for msg in messages:
        api_client.post("/mailbox/send", json=msg)

    # Now check status
    response = api_client.get("/mailbox")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 2
    assert len(data["messages"]) == 2
    assert data["total_messages_received"] == 2

    # Verify messages are sorted by priority (highest first)
    assert data["messages"][0]["priority"] == 2
    assert data["messages"][1]["priority"] == 1


def test_get_mailbox_message_previews(api_client, temp_dir):
    """Test that message previews contain expected fields."""
    # Send a message
    api_client.post(
        "/mailbox/send",
        json={"content": "Test message content", "sender": "test-sender", "priority": 2},
    )

    response = api_client.get("/mailbox")

    assert response.status_code == 200
    data = response.json()
    preview = data["messages"][0]

    assert "id" in preview
    assert preview["sender"] == "test-sender"
    assert preview["priority"] == 2
    assert "timestamp" in preview
    assert "content_preview" in preview


def test_get_mailbox_content_preview_truncation(api_client, temp_dir):
    """Test that long content is truncated in preview."""
    long_content = "A" * 200  # Longer than default preview length

    api_client.post("/mailbox/send", json={"content": long_content})

    response = api_client.get("/mailbox")

    assert response.status_code == 200
    data = response.json()
    preview = data["messages"][0]["content_preview"]

    # Preview should be truncated with ellipsis
    assert len(preview) <= 103  # 100 chars + "..."
    assert preview.endswith("...")


# =============================================================================
# DELETE /mailbox Tests
# =============================================================================


def test_delete_mailbox_empty(api_client, temp_dir):
    """Test DELETE /mailbox when mailbox is empty."""
    response = api_client.delete("/mailbox")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["messages_cleared"] == 0
    assert "Cleared 0 message" in data["message"]


def test_delete_mailbox_with_messages(api_client, temp_dir):
    """Test DELETE /mailbox clears all messages."""
    # First send some messages
    for i in range(5):
        api_client.post("/mailbox/send", json={"content": f"Message {i}"})

    # Verify messages exist
    status_response = api_client.get("/mailbox")
    assert status_response.json()["count"] == 5

    # Clear the mailbox
    response = api_client.delete("/mailbox")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["messages_cleared"] == 5
    assert "Cleared 5 message" in data["message"]

    # Verify mailbox is now empty
    status_response = api_client.get("/mailbox")
    assert status_response.json()["count"] == 0


def test_delete_mailbox_preserves_total_received(api_client, temp_dir):
    """Test that clearing mailbox preserves total_messages_received count."""
    # Send messages
    for i in range(3):
        api_client.post("/mailbox/send", json={"content": f"Message {i}"})

    # Clear the mailbox
    api_client.delete("/mailbox")

    # Check that total_messages_received is preserved
    response = api_client.get("/mailbox")
    data = response.json()
    assert data["count"] == 0
    assert data["total_messages_received"] == 3


def test_delete_mailbox_updates_last_checked(api_client, temp_dir):
    """Test that clearing mailbox updates last_checked timestamp."""
    # Send a message
    api_client.post("/mailbox/send", json={"content": "Test message"})

    # Clear the mailbox
    api_client.delete("/mailbox")

    # Check that last_checked is now set
    response = api_client.get("/mailbox")
    data = response.json()
    assert data["last_checked"] is not None


# =============================================================================
# Integration Tests
# =============================================================================


def test_mailbox_full_workflow(api_client, temp_dir):
    """Test complete mailbox workflow: send, check, clear."""
    # 1. Send multiple messages
    messages = [
        {"content": "Urgent: Fix bug", "sender": "user", "priority": 3},
        {"content": "Add feature", "sender": "pm", "priority": 1},
        {"content": "Review code", "sender": "reviewer", "priority": 2},
    ]

    for msg in messages:
        response = api_client.post("/mailbox/send", json=msg)
        assert response.status_code == 200

    # 2. Check status - should show 3 messages sorted by priority
    response = api_client.get("/mailbox")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert data["messages"][0]["priority"] == 3  # Urgent first
    assert data["messages"][1]["priority"] == 2
    assert data["messages"][2]["priority"] == 1

    # 3. Clear mailbox
    response = api_client.delete("/mailbox")
    assert response.status_code == 200
    assert response.json()["messages_cleared"] == 3

    # 4. Verify empty but total_received preserved
    response = api_client.get("/mailbox")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["total_messages_received"] == 3

    # 5. Send more messages
    api_client.post("/mailbox/send", json={"content": "New message"})

    response = api_client.get("/mailbox")
    data = response.json()
    assert data["count"] == 1
    assert data["total_messages_received"] == 4  # Cumulative count


def test_mailbox_concurrent_sends(api_client, temp_dir):
    """Test that multiple sends are handled correctly."""
    # Send 10 messages rapidly
    for i in range(10):
        response = api_client.post(
            "/mailbox/send",
            json={"content": f"Message {i}", "sender": f"agent-{i}"},
        )
        assert response.status_code == 200

    # Verify all messages were stored
    response = api_client.get("/mailbox")
    assert response.json()["count"] == 10


def test_mailbox_no_task_required(api_client, temp_dir):
    """Test that mailbox works without an active task."""
    # Don't create any task state files

    # Should still be able to send messages
    response = api_client.post(
        "/mailbox/send",
        json={"content": "Message without active task"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Should be able to check status
    response = api_client.get("/mailbox")
    assert response.status_code == 200
    assert response.json()["count"] == 1

    # Should be able to clear
    response = api_client.delete("/mailbox")
    assert response.status_code == 200


# =============================================================================
# Model Validation Tests
# =============================================================================


def test_send_message_request_validation():
    """Test SendMailboxMessageRequest model validation."""
    from claude_task_master.api.models import SendMailboxMessageRequest

    # Valid request with all fields
    request = SendMailboxMessageRequest(
        content="Test content",
        sender="test-sender",
        priority=2,
        metadata={"key": "value"},
    )
    assert request.content == "Test content"
    assert request.sender == "test-sender"
    assert request.priority == 2
    assert request.metadata == {"key": "value"}

    # Valid request with minimal fields
    request = SendMailboxMessageRequest(content="Just content")
    assert request.content == "Just content"
    assert request.sender == "anonymous"
    assert request.priority == 1
    assert request.metadata is None


def test_mailbox_message_preview_model():
    """Test MailboxMessagePreview model."""
    from claude_task_master.api.models import MailboxMessagePreview

    preview = MailboxMessagePreview(
        id="test-id",
        sender="test-sender",
        content_preview="Preview text",
        priority=2,
        timestamp=datetime.now(),
    )
    assert preview.id == "test-id"
    assert preview.sender == "test-sender"
    assert preview.content_preview == "Preview text"
    assert preview.priority == 2


def test_mailbox_status_response_model():
    """Test MailboxStatusResponse model."""
    from claude_task_master.api.models import MailboxStatusResponse

    response = MailboxStatusResponse(
        success=True,
        count=5,
        messages=[],
        total_messages_received=10,
    )
    assert response.success is True
    assert response.count == 5
    assert response.total_messages_received == 10


def test_clear_mailbox_response_model():
    """Test ClearMailboxResponse model."""
    from claude_task_master.api.models import ClearMailboxResponse

    response = ClearMailboxResponse(
        success=True,
        messages_cleared=5,
        message="Cleared 5 messages",
    )
    assert response.success is True
    assert response.messages_cleared == 5
    assert response.message == "Cleared 5 messages"
