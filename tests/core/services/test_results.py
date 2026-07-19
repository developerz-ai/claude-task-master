"""Unit tests for the transport-neutral service result type."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from claude_task_master.core.services.results import ServiceOutcome, ServiceResult


class TestServiceOutcome:
    """The outcome enum used by every service method."""

    def test_is_str_enum(self) -> None:
        """Members are strings whose value drives serialisation."""
        assert isinstance(ServiceOutcome.OK, str)
        assert ServiceOutcome.OK.value == "ok"
        assert ServiceOutcome.NOT_FOUND.value == "not_found"

    def test_covers_all_transport_codes(self) -> None:
        """Every outcome a transport must map is present."""
        assert {o.value for o in ServiceOutcome} == {
            "ok",
            "not_found",
            "invalid",
            "conflict",
            "forbidden",
            "error",
        }


class TestServiceResultConstructors:
    """Each classmethod builds a result with the right outcome and fields."""

    def test_ok_sets_outcome_and_payload(self) -> None:
        """``ok`` carries the success payload and marks success."""
        result = ServiceResult.ok(data={"plan": "x"}, message="done")
        assert result.outcome is ServiceOutcome.OK
        assert result.success is True
        assert result.data == {"plan": "x"}
        assert result.message == "done"
        assert result.error is None

    def test_not_found(self) -> None:
        """``not_found`` sets the NOT_FOUND outcome and is not a success."""
        result = ServiceResult.not_found(message="No plan found")
        assert result.outcome is ServiceOutcome.NOT_FOUND
        assert result.success is False
        assert result.message == "No plan found"

    def test_invalid_carries_error_and_data(self) -> None:
        """``invalid`` records both a message and an error detail."""
        result = ServiceResult.invalid(
            message="Cannot stop task", error="details", data={"previous_status": "success"}
        )
        assert result.outcome is ServiceOutcome.INVALID
        assert result.success is False
        assert result.error == "details"
        assert result.data == {"previous_status": "success"}

    def test_conflict(self) -> None:
        """``conflict`` maps a resource-conflict outcome."""
        assert ServiceResult.conflict().outcome is ServiceOutcome.CONFLICT

    def test_forbidden(self) -> None:
        """``forbidden`` maps an authorization refusal."""
        result = ServiceResult.forbidden(message="auth required", error="authentication_required")
        assert result.outcome is ServiceOutcome.FORBIDDEN
        assert result.error == "authentication_required"

    def test_failed(self) -> None:
        """``failed`` maps an unexpected internal error."""
        result = ServiceResult.failed(error="boom")
        assert result.outcome is ServiceOutcome.ERROR
        assert result.success is False
        assert result.error == "boom"

    @pytest.mark.parametrize(
        "factory",
        [
            ServiceResult.ok,
            ServiceResult.not_found,
            ServiceResult.invalid,
            ServiceResult.conflict,
            ServiceResult.forbidden,
            ServiceResult.failed,
        ],
    )
    def test_default_data_is_independent(self, factory: Callable[[], ServiceResult]) -> None:
        """Omitted ``data`` defaults to a fresh empty dict, never a shared one."""
        first = factory()
        second = factory()
        first.data["mutated"] = True
        assert second.data == {}

    def test_only_ok_is_success(self) -> None:
        """``success`` is true for OK alone."""
        assert ServiceResult.ok().success is True
        for factory in (
            ServiceResult.not_found,
            ServiceResult.invalid,
            ServiceResult.conflict,
            ServiceResult.forbidden,
            ServiceResult.failed,
        ):
            assert factory().success is False
