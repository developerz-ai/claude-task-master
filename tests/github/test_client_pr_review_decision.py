"""Tests for the reviewDecision field on PR status (issue #146).

The PR-status GraphQL query selected ``reviewThreads`` only, so nothing in
claudetm could tell an approved PR from one a reviewer had actively pushed back
on. The field is now selected and carried on :class:`PRStatus`; anything that is
not a usable string degrades to ``None`` ("no decision"), because a review-state
lookup must never be able to block a merge.
"""

from __future__ import annotations

from typing import Any

from claude_task_master.github.client_pr_helpers import (
    _build_pr_status_query,
    _parse_pr_status_response,
)


def _pr_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "baseRefName": "main",
        "headRefName": "feat/x",
        "title": "t",
        "url": "https://example.invalid/1",
        "commits": {"nodes": []},
        "reviewThreads": {"pageInfo": {"hasNextPage": False}, "nodes": []},
    }
    data.update(overrides)
    return data


class TestReviewDecisionDegradesSafely:
    """An unreadable decision must look like "no decision", never like a verdict."""

    def test_missing_field_is_none(self):
        status = _parse_pr_status_response(1, _pr_data())

        assert status.review_decision is None

    def test_null_decision_is_none(self):
        status = _parse_pr_status_response(1, _pr_data(reviewDecision=None))

        assert status.review_decision is None

    def test_empty_string_is_none(self):
        status = _parse_pr_status_response(1, _pr_data(reviewDecision=""))

        assert status.review_decision is None

    def test_non_string_is_none(self):
        status = _parse_pr_status_response(1, _pr_data(reviewDecision={"unexpected": True}))

        assert status.review_decision is None


class TestReviewDecisionIsCarried:
    """The three states GitHub reports survive parsing verbatim."""

    def test_changes_requested(self):
        status = _parse_pr_status_response(1, _pr_data(reviewDecision="CHANGES_REQUESTED"))

        assert status.review_decision == "CHANGES_REQUESTED"

    def test_approved(self):
        status = _parse_pr_status_response(1, _pr_data(reviewDecision="APPROVED"))

        assert status.review_decision == "APPROVED"

    def test_review_required(self):
        status = _parse_pr_status_response(1, _pr_data(reviewDecision="REVIEW_REQUIRED"))

        assert status.review_decision == "REVIEW_REQUIRED"

    def test_query_selects_the_field(self):
        assert "reviewDecision" in _build_pr_status_query()


class TestWhoRequestedChanges:
    """Regression: `reviewDecision` never says *who*, so a bot read as a human.

    A review bot's CHANGES_REQUESTED is indistinguishable from a person's in the
    aggregate decision, and the merge gate blocked on it forever — no bot returns
    to dismiss its own review after claudetm resolves its threads.
    """

    def _status(self, nodes):
        return _parse_pr_status_response(7, {"latestOpinionatedReviews": {"nodes": nodes}})

    def test_bot_reviewer_is_reported_as_a_bot(self):
        status = self._status(
            [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"__typename": "Bot", "login": "coderabbitai"},
                }
            ]
        )
        assert status.changes_requested_by == ["coderabbitai"]
        assert status.changes_requested_bots == ["coderabbitai"]

    def test_human_reviewer_is_not_a_bot(self):
        status = self._status(
            [{"state": "CHANGES_REQUESTED", "author": {"__typename": "User", "login": "sebi"}}]
        )
        assert status.changes_requested_by == ["sebi"]
        assert status.changes_requested_bots == []

    def test_bot_login_suffix_counts_even_when_typed_user(self):
        status = self._status(
            [{"state": "CHANGES_REQUESTED", "author": {"__typename": "User", "login": "dep[bot]"}}]
        )
        assert status.changes_requested_bots == ["dep[bot]"]

    def test_approvals_are_not_collected(self):
        status = self._status(
            [{"state": "APPROVED", "author": {"__typename": "User", "login": "sebi"}}]
        )
        assert status.changes_requested_by == []

    def test_missing_field_reads_as_unknown_not_as_nobody(self):
        """Both lists empty is what makes the merge gate fall back to blocking."""
        status = _parse_pr_status_response(7, {})
        assert status.changes_requested_by == []
        assert status.changes_requested_bots == []

    def test_malformed_nodes_are_skipped_without_raising(self):
        status = self._status(
            [
                None,
                {},
                {"state": "CHANGES_REQUESTED"},
                {"state": "CHANGES_REQUESTED", "author": None},
            ]
        )
        assert status.changes_requested_by == []
