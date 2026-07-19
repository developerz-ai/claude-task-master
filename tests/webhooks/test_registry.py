"""Tests for the durable, lock-protected WebhookRegistry.

Covers the storage guarantees the registry exists to provide:

- tolerant, lock-free reads (missing / corrupt / malformed files),
- atomic read-modify-write transactions that serialise concurrent writers,
- write-abort when a transaction body raises,
- backward-compatible on-disk format,
- event-subscription filtering for the orchestrator fan-out.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from claude_task_master.webhooks.events import EventType
from claude_task_master.webhooks.registry import (
    WEBHOOKS_FILE,
    WebhookRegistry,
)

# =============================================================================
# Helpers / Fixtures
# =============================================================================


def _record(url: str, *, enabled: bool = True, events: list[str] | None = None) -> dict:
    """Build a stored webhook record for tests."""
    return {
        "url": url,
        "secret": None,
        "events": events,
        "enabled": enabled,
        "name": None,
        "description": None,
        "timeout": 30.0,
        "max_retries": 3,
        "verify_ssl": True,
        "headers": {},
        "created_at": "2026-07-19T00:00:00",
        "updated_at": "2026-07-19T00:00:00",
    }


@pytest.fixture
def registry(state_dir: Path) -> WebhookRegistry:
    """A registry bound to a fresh state directory."""
    return WebhookRegistry(state_dir)


# =============================================================================
# Reads
# =============================================================================


class TestLoad:
    """Lock-free, corruption-tolerant reads."""

    def test_missing_file_returns_empty(self, registry: WebhookRegistry) -> None:
        """A registry with no file on disk loads as empty."""
        assert registry.load() == {}

    def test_roundtrip_load_after_write(self, registry: WebhookRegistry) -> None:
        """Records written in a transaction are visible on the next load."""
        with registry.transaction() as webhooks:
            webhooks["wh_1"] = _record("https://example.com/a")
        assert list(registry.load()) == ["wh_1"]

    def test_corrupt_json_returns_empty(self, registry: WebhookRegistry) -> None:
        """A truncated/garbage file is tolerated as an empty registry."""
        registry.storage_path.write_text("{not valid json", encoding="utf-8")
        assert registry.load() == {}

    def test_non_dict_top_level_returns_empty(self, registry: WebhookRegistry) -> None:
        """A JSON list at the top level is treated as empty, not an error."""
        registry.storage_path.write_text("[1, 2, 3]", encoding="utf-8")
        assert registry.load() == {}

    def test_non_dict_webhooks_key_returns_empty(self, registry: WebhookRegistry) -> None:
        """A malformed 'webhooks' value is treated as empty."""
        registry.storage_path.write_text('{"webhooks": []}', encoding="utf-8")
        assert registry.load() == {}


class TestGet:
    """Single-record lookup."""

    def test_get_present(self, registry: WebhookRegistry) -> None:
        """get() returns the stored record for a known id."""
        with registry.transaction() as webhooks:
            webhooks["wh_1"] = _record("https://example.com/a")
        record = registry.get("wh_1")
        assert record is not None
        assert record["url"] == "https://example.com/a"

    def test_get_absent(self, registry: WebhookRegistry) -> None:
        """get() returns None for an unknown id."""
        assert registry.get("nope") is None


# =============================================================================
# Transactions
# =============================================================================


class TestTransaction:
    """Atomic, lock-serialised read-modify-write."""

    def test_write_uses_backward_compatible_envelope(self, registry: WebhookRegistry) -> None:
        """The on-disk format stays {'webhooks': {...}, 'updated_at': ...}."""
        with registry.transaction() as webhooks:
            webhooks["wh_1"] = _record("https://example.com/a")

        raw = json.loads(registry.storage_path.read_text(encoding="utf-8"))
        assert set(raw) == {"webhooks", "updated_at"}
        assert "wh_1" in raw["webhooks"]

    def test_writes_land_in_expected_file(self, registry: WebhookRegistry, state_dir: Path) -> None:
        """The registry writes to <state_dir>/webhooks.json."""
        with registry.transaction() as webhooks:
            webhooks["wh_1"] = _record("https://example.com/a")
        assert (state_dir / WEBHOOKS_FILE).exists()

    def test_sequential_transactions_accumulate(self, registry: WebhookRegistry) -> None:
        """Each transaction loads the latest state (RMW under lock)."""
        with registry.transaction() as webhooks:
            webhooks["wh_1"] = _record("https://example.com/a")
        with registry.transaction() as webhooks:
            webhooks["wh_2"] = _record("https://example.com/b")
        assert set(registry.load()) == {"wh_1", "wh_2"}

    def test_exception_aborts_write(self, registry: WebhookRegistry) -> None:
        """A raise inside the body leaves the on-disk registry untouched."""
        with registry.transaction() as webhooks:
            webhooks["wh_1"] = _record("https://example.com/a")

        with pytest.raises(RuntimeError):
            with registry.transaction() as webhooks:
                webhooks["wh_2"] = _record("https://example.com/b")
                raise RuntimeError("boom")

        # wh_2 must NOT have been persisted.
        assert set(registry.load()) == {"wh_1"}

    def test_concurrent_transactions_do_not_lose_writes(self, registry: WebhookRegistry) -> None:
        """Two threads each adding a webhook both survive (flock serialises)."""
        barrier = threading.Barrier(2)

        def add(webhook_id: str, url: str) -> None:
            barrier.wait()
            with registry.transaction() as webhooks:
                webhooks[webhook_id] = _record(url)

        t1 = threading.Thread(target=add, args=("wh_1", "https://example.com/a"))
        t2 = threading.Thread(target=add, args=("wh_2", "https://example.com/b"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert set(registry.load()) == {"wh_1", "wh_2"}


# =============================================================================
# Fan-out filtering
# =============================================================================


class TestConfigsForEvent:
    """Subscription filtering for the orchestrator fan-out."""

    def test_no_filter_receives_all_events(self, registry: WebhookRegistry) -> None:
        """A webhook with events=None is subscribed to every event."""
        with registry.transaction() as webhooks:
            webhooks["wh_all"] = _record("https://example.com/all", events=None)

        matches = registry.configs_for_event(EventType.RUN_STARTED)
        assert [wid for wid, _ in matches] == ["wh_all"]

    def test_filters_by_subscription(self, registry: WebhookRegistry) -> None:
        """Only webhooks subscribed to the event are returned."""
        with registry.transaction() as webhooks:
            webhooks["wh_pr"] = _record("https://example.com/pr", events=["pr.created"])
            webhooks["wh_task"] = _record("https://example.com/task", events=["task.completed"])

        matches = registry.configs_for_event(EventType.PR_CREATED)
        assert [wid for wid, _ in matches] == ["wh_pr"]

    def test_disabled_webhook_excluded(self, registry: WebhookRegistry) -> None:
        """Disabled webhooks never match, even when subscribed."""
        with registry.transaction() as webhooks:
            webhooks["wh_off"] = _record("https://example.com/off", enabled=False)

        assert registry.configs_for_event(EventType.RUN_STARTED) == []

    def test_accepts_event_string(self, registry: WebhookRegistry) -> None:
        """configs_for_event accepts the event's string value too."""
        with registry.transaction() as webhooks:
            webhooks["wh_all"] = _record("https://example.com/all")

        matches = registry.configs_for_event("run.started")
        assert [wid for wid, _ in matches] == ["wh_all"]

    def test_invalid_record_skipped(self, registry: WebhookRegistry) -> None:
        """A record that fails validation is skipped, not fatal, for fan-out."""
        with registry.transaction() as webhooks:
            webhooks["wh_bad"] = {"enabled": True}  # missing required 'url'
            webhooks["wh_ok"] = _record("https://example.com/ok")

        matches = registry.configs_for_event(EventType.RUN_STARTED)
        assert [wid for wid, _ in matches] == ["wh_ok"]

    def test_config_carries_delivery_settings(self, registry: WebhookRegistry) -> None:
        """The returned WebhookConfig exposes the stored delivery settings."""
        record = _record("https://example.com/a")
        record["timeout"] = 12.0
        record["max_retries"] = 7
        with registry.transaction() as webhooks:
            webhooks["wh_1"] = record

        (_, config) = registry.configs_for_event(EventType.RUN_STARTED)[0]
        assert config.timeout == 12.0
        assert config.max_retries == 7
