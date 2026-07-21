"""Tests for tolerated (non-blocking) CI check failures.

Regression: a rate-limited CodeRabbit status ("CodeRabbit" / FAILURE /
"Review rate limited") turned the whole rollup red, so the orchestrator ran a
fix session and then looped on a check no commit can turn green.
"""

from __future__ import annotations

import pytest

from claude_task_master.github.check_tolerance import (
    TOLERATED_FAILURES_ENV,
    is_failed_check,
    is_tolerated_failure,
    tolerated_reason,
)
from claude_task_master.github.client_pr_helpers import (
    _parse_check_contexts,
    _parse_pr_status_response,
)


def _status_context(context: str, state: str, description: str | None = None) -> dict:
    """Build a normalized StatusContext check detail."""
    return {
        "name": context,
        "context": context,
        "status": state,
        "conclusion": state,
        "description": description,
        "url": None,
    }


def _check_run(name: str, conclusion: str) -> dict:
    """Build a normalized CheckRun check detail."""
    return {"name": name, "status": "COMPLETED", "conclusion": conclusion, "url": "https://ci"}


class TestToleranceRules:
    """The whitelist matches exactly one CodeRabbit message and nothing else."""

    def test_rate_limited_coderabbit_is_tolerated(self):
        check = _status_context("CodeRabbit", "FAILURE", "Review rate limited")
        assert is_tolerated_failure(check)
        assert not is_failed_check(check)
        assert "quota" in (tolerated_reason(check) or "")

    def test_matching_is_case_and_whitespace_insensitive(self):
        check = _status_context("  coderabbit ", "FAILURE", "  REVIEW RATE LIMITED  ")
        assert is_tolerated_failure(check)

    @pytest.mark.parametrize(
        "description",
        [
            "Review failed",
            "1 issue found",
            "Review rate limited soon",  # not the exact message
            "",
            None,
        ],
    )
    def test_other_coderabbit_failures_still_fail(self, description):
        check = _status_context("CodeRabbit", "FAILURE", description)
        assert not is_tolerated_failure(check)
        assert is_failed_check(check)

    def test_other_checks_with_the_same_message_still_fail(self):
        check = _status_context("SomeOtherBot", "FAILURE", "Review rate limited")
        assert is_failed_check(check)

    def test_check_runs_are_never_tolerated(self):
        assert is_failed_check(_check_run("Tests", "FAILURE"))

    def test_passing_check_is_not_a_failure(self):
        assert not is_failed_check(_check_run("Tests", "SUCCESS"))


class TestEnvironmentRules:
    """Extra exceptions can be declared without a release."""

    def test_env_rule_is_honoured(self, monkeypatch):
        monkeypatch.setenv(TOLERATED_FAILURES_ENV, "some-bot=quota exceeded")
        assert is_tolerated_failure(_status_context("some-bot", "FAILURE", "Quota exceeded"))
        assert is_failed_check(_status_context("some-bot", "FAILURE", "Broken"))

    def test_multiple_env_rules(self, monkeypatch):
        monkeypatch.setenv(TOLERATED_FAILURES_ENV, "a=one; b=two")
        assert is_tolerated_failure(_status_context("a", "FAILURE", "one"))
        assert is_tolerated_failure(_status_context("b", "FAILURE", "two"))

    def test_malformed_env_is_ignored(self, monkeypatch):
        monkeypatch.setenv(TOLERATED_FAILURES_ENV, "garbage;;=x;y=")
        # Built-in rules still work, malformed entries do not raise.
        assert is_tolerated_failure(_status_context("CodeRabbit", "FAILURE", "Review rate limited"))


class TestPRStatusParsing:
    """The rollup state is recomputed so a rate-limited bot cannot fail a PR."""

    @staticmethod
    def _pr_data(contexts: list[dict], rollup_state: str) -> dict:
        return {
            "state": "OPEN",
            "mergeable": "MERGEABLE",
            "baseRefName": "main",
            "commits": {
                "nodes": [
                    {
                        "commit": {
                            "statusCheckRollup": {
                                "state": rollup_state,
                                "contexts": {"pageInfo": {"hasNextPage": False}, "nodes": contexts},
                            }
                        }
                    }
                ]
            },
            "reviewThreads": {"pageInfo": {"hasNextPage": False}, "nodes": []},
        }

    def test_description_is_parsed_from_status_context(self):
        parsed = _parse_check_contexts(
            [
                {
                    "__typename": "StatusContext",
                    "context": "CodeRabbit",
                    "state": "FAILURE",
                    "description": "Review rate limited",
                    "targetUrl": None,
                }
            ]
        )
        assert parsed[0]["description"] == "Review rate limited"

    def test_rate_limited_bot_alone_does_not_fail_ci(self):
        """Regression: green tests + rate-limited CodeRabbit reported FAILURE."""
        contexts: list[dict] = [
            {
                "__typename": "CheckRun",
                "name": "Tests",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "detailsUrl": "https://ci",
            },
            {
                "__typename": "StatusContext",
                "context": "CodeRabbit",
                "state": "FAILURE",
                "description": "Review rate limited",
                "targetUrl": None,
            },
        ]
        status = _parse_pr_status_response(1, self._pr_data(contexts, "FAILURE"))

        assert status.ci_state == "SUCCESS"
        assert status.checks_failed == 0
        assert status.checks_passed == 1
        assert status.checks_skipped == 1

    def test_real_failure_alongside_rate_limit_still_fails(self):
        contexts: list[dict] = [
            {
                "__typename": "CheckRun",
                "name": "Tests",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "detailsUrl": "https://ci",
            },
            {
                "__typename": "StatusContext",
                "context": "CodeRabbit",
                "state": "FAILURE",
                "description": "Review rate limited",
                "targetUrl": None,
            },
        ]
        status = _parse_pr_status_response(1, self._pr_data(contexts, "FAILURE"))

        assert status.ci_state == "FAILURE"
        assert status.checks_failed == 1

    def test_rate_limit_with_checks_still_running_stays_pending(self):
        contexts: list[dict] = [
            {
                "__typename": "CheckRun",
                "name": "Tests",
                "status": "IN_PROGRESS",
                "conclusion": None,
                "detailsUrl": "https://ci",
            },
            {
                "__typename": "StatusContext",
                "context": "CodeRabbit",
                "state": "FAILURE",
                "description": "Review rate limited",
                "targetUrl": None,
            },
        ]
        status = _parse_pr_status_response(1, self._pr_data(contexts, "FAILURE"))

        assert status.ci_state == "PENDING"

    def test_genuine_success_is_untouched(self):
        contexts: list[dict] = [
            {
                "__typename": "CheckRun",
                "name": "Tests",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "detailsUrl": "https://ci",
            },
        ]
        status = _parse_pr_status_response(1, self._pr_data(contexts, "SUCCESS"))

        assert status.ci_state == "SUCCESS"
        assert status.checks_failed == 0
