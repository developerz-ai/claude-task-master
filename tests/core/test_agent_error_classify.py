"""Tests for agent_error_classify - mapping raw SDK exceptions onto AgentError.

This module contains tests for:
- The structured path (``ResultError``'s ``api_error_status`` and friends)
- ``result_error_fields`` / ``searchable_error_text`` field extraction
- The text path (token-boundary rules over the message plus its payload)
- The two loose-substring regressions the module exists to prevent
- Importability with ``claude_agent_sdk`` absent

The classification decides whether an unattended run retries or dies, so each
case asserts the concrete type - membership in TRANSIENT_ERRORS is what the
retry layer branches on.
"""

import importlib
import inspect
from typing import Any
from unittest.mock import patch

import pytest

from claude_task_master.core import agent_error_classify
from claude_task_master.core.agent_error_classify import (
    classify_api_error,
    result_error_fields,
    searchable_error_text,
)
from claude_task_master.core.agent_exceptions import (
    TRANSIENT_ERRORS,
    APIAuthenticationError,
    APIConnectionError,
    APIRateLimitError,
    APIServerError,
    APITimeoutError,
    ContentFilterError,
    ModelUnavailableError,
    QueryExecutionError,
)

# =============================================================================
# Helpers
# =============================================================================


class FakeResultError(Exception):
    """Duck-typed stand-in for the SDK's ResultError.

    The module reads the payload with getattr rather than by importing the SDK,
    so the main path is exercised with a fake. One test below pins the same
    contract against a genuinely constructed ``claude_agent_sdk.ResultError``.
    """

    def __init__(self, message: str = "", **payload: Any):
        super().__init__(message)
        for name, value in payload.items():
            setattr(self, name, value)


#: What str(ResultError) actually looks like - it names the subtype and nothing
#: else, which is why the payload has to be folded into the searched text.
TERMINAL_MESSAGE = "Claude Code returned an error result: error_during_execution (exit code: 1)"


# =============================================================================
# result_error_fields Tests
# =============================================================================


class TestResultErrorFields:
    """Tests for result_error_fields payload extraction."""

    def test_plain_exception_yields_empty_dict(self):
        """Test a plain Exception carries no structured payload."""
        assert result_error_fields(Exception("boom")) == {}

    def test_all_fields_extracted(self):
        """Test every supported field is picked up off the exception."""
        error = FakeResultError(
            TERMINAL_MESSAGE,
            api_error_status=529,
            subtype="error_during_execution",
            terminal_reason="api_error",
            result="API Error: 529 overloaded_error",
            errors=["Connection closed mid-response"],
        )
        assert result_error_fields(error) == {
            "api_error_status": 529,
            "subtype": "error_during_execution",
            "terminal_reason": "api_error",
            "result": "API Error: 529 overloaded_error",
            "errors": ["Connection closed mid-response"],
        }

    def test_status_as_string_is_dropped(self):
        """Test a wrong-typed api_error_status is ignored, not coerced."""
        error = FakeResultError("boom", api_error_status="429")
        assert "api_error_status" not in result_error_fields(error)

    def test_bool_status_is_dropped(self):
        """Test a bool api_error_status is not read as HTTP status 1.

        bool is an int subclass, so a naive isinstance(status, int) would let
        True through and classify it as a status the mapper has no verdict for
        - or worse, a real one.
        """
        error = FakeResultError("boom", api_error_status=True)
        assert "api_error_status" not in result_error_fields(error)

    def test_errors_not_a_list_is_dropped(self):
        """Test a non-list errors field is ignored."""
        error = FakeResultError("boom", errors="Connection closed mid-response")
        assert "errors" not in result_error_fields(error)

    def test_non_string_entries_inside_errors_are_dropped(self):
        """Test only string entries survive inside errors."""
        error = FakeResultError("boom", errors=[1, None, "real one", ""])
        assert result_error_fields(error)["errors"] == ["real one"]

    def test_all_entries_dropped_leaves_no_errors_key(self):
        """Test an errors list with nothing usable in it is omitted entirely."""
        error = FakeResultError("boom", errors=[None, 0, ""])
        assert "errors" not in result_error_fields(error)

    def test_empty_strings_are_dropped(self):
        """Test empty subtype/result/terminal_reason values are omitted."""
        error = FakeResultError("boom", subtype="", terminal_reason="", result="")
        assert result_error_fields(error) == {}


# =============================================================================
# searchable_error_text Tests
# =============================================================================


class TestSearchableErrorText:
    """Tests for searchable_error_text."""

    def test_plain_exception_is_just_its_message(self):
        """Test text for a payload-less error is the lower-cased message."""
        error = Exception("Some UNKNOWN Error")
        assert searchable_error_text(error, {}) == "some unknown error"

    def test_payload_prose_is_folded_in(self):
        """Test result and errors prose joins the searched text.

        str(ResultError) names only the subtype; the string that says what
        actually failed lives in result/errors. Folding it in is what lets a
        text rule fire on a ResultError at all.
        """
        error = FakeResultError(
            TERMINAL_MESSAGE,
            result="API Error: 529 overloaded_error",
            errors=["Connection closed mid-response"],
        )
        text = searchable_error_text(error, result_error_fields(error))
        assert "529 overloaded_error" in text
        assert "connection closed mid-response" in text

    def test_text_is_lower_cased(self):
        """Test payload prose is lower-cased along with the message."""
        error = FakeResultError("BOOM", errors=["Connection CLOSED"])
        text = searchable_error_text(error, result_error_fields(error))
        assert text == "boom\nconnection closed"

    def test_subtype_and_reason_are_not_searched_as_prose(self):
        """Test only result/errors are folded in, per the module contract."""
        error = FakeResultError("boom", subtype="error_during_execution")
        text = searchable_error_text(error, result_error_fields(error))
        assert text == "boom"


# =============================================================================
# Structured Path (api_error_status) Tests
# =============================================================================


class TestStructuredStatusClassification:
    """Tests for classification driven by the result payload's HTTP status."""

    @pytest.mark.parametrize(
        ("status", "expected", "status_code"),
        [
            (429, APIRateLimitError, None),
            (401, APIAuthenticationError, None),
            (403, APIAuthenticationError, None),
            (408, APITimeoutError, None),
            (504, APITimeoutError, None),
            (500, APIServerError, 500),
            (503, APIServerError, 503),
            (529, APIServerError, 529),
        ],
    )
    def test_status_maps_to_type(self, status, expected, status_code):
        """Test each decisive status maps to its typed error.

        529 is Anthropic's "overloaded" status and the real-world case the old
        text rules missed entirely: it never appears in str(ResultError), so
        only the structured payload can see it.
        """
        error = FakeResultError(TERMINAL_MESSAGE, api_error_status=status)
        classified = classify_api_error(error)
        assert isinstance(classified, expected)
        if status_code is not None:
            assert classified.status_code == status_code

    def test_504_is_a_timeout_not_a_server_error(self):
        """Test a gateway timeout is reported as a timeout, not a bare 5xx."""
        error = FakeResultError(TERMINAL_MESSAGE, api_error_status=504)
        classified = classify_api_error(error)
        assert isinstance(classified, APITimeoutError)
        assert not isinstance(classified, APIServerError)

    def test_529_is_transient(self):
        """Test an overloaded API is retryable, which is the whole point."""
        error = FakeResultError(TERMINAL_MESSAGE, api_error_status=529)
        assert isinstance(classify_api_error(error), TRANSIENT_ERRORS)

    def test_404_with_model_in_payload_is_model_unavailable(self):
        """Test a model 404 routes to the fallback chain."""
        error = FakeResultError(
            TERMINAL_MESSAGE,
            api_error_status=404,
            result="API Error: 404 model claude-nope not_found",
        )
        assert isinstance(classify_api_error(error), ModelUnavailableError)

    def test_404_without_model_falls_through_to_text_rules(self):
        """Test a non-model 404 is not treated as a bad model id."""
        error = FakeResultError(
            TERMINAL_MESSAGE,
            api_error_status=404,
            result="API Error: 404 no such endpoint",
        )
        classified = classify_api_error(error)
        assert not isinstance(classified, ModelUnavailableError)
        assert isinstance(classified, QueryExecutionError)

    @pytest.mark.parametrize("status", [400, 418])
    def test_status_without_a_verdict_falls_through_to_text_rules(self, status):
        """Test a status the mapper has no opinion on defers to the prose."""
        error = FakeResultError(
            TERMINAL_MESSAGE,
            api_error_status=status,
            errors=["Connection closed mid-response"],
        )
        assert isinstance(classify_api_error(error), APIConnectionError)

    def test_bool_status_is_ignored_by_the_classifier(self):
        """Test api_error_status=True does not classify as HTTP status 1."""
        error = FakeResultError("Some unknown error", api_error_status=True)
        classified = classify_api_error(error)
        assert type(classified) is QueryExecutionError

    def test_connection_prose_in_errors_classifies_as_connection(self):
        """Test payload-only prose reaches the text rules.

        "Connection closed mid-response" lives in ``errors`` and nowhere in
        str(error); it must still classify as a retryable connection error.
        """
        error = FakeResultError(
            TERMINAL_MESSAGE,
            subtype="error_during_execution",
            errors=["Connection closed mid-response"],
        )
        assert isinstance(classify_api_error(error), APIConnectionError)

    @pytest.mark.parametrize("status", [429, 401, 403, 408, 504, 500, 529])
    def test_structured_path_keeps_the_raw_exception(self, status):
        """Test the raw exception stays reachable on the structured path."""
        error = FakeResultError(TERMINAL_MESSAGE, api_error_status=status)
        classified = classify_api_error(error)
        assert isinstance(classified, QueryExecutionError)
        assert classified.original_error is error

    def test_text_path_keeps_the_raw_exception(self):
        """Test the raw exception stays reachable on the text path too."""
        error = Exception("Connection refused")
        classified = classify_api_error(error)
        assert isinstance(classified, QueryExecutionError)
        assert classified.original_error is error


# =============================================================================
# Real claude_agent_sdk.ResultError Tests
# =============================================================================


class TestRealResultError:
    """Pins the contract against a genuinely constructed SDK ResultError."""

    @staticmethod
    def _build() -> Any:
        """Build the real ResultError the SDK raises for an API failure."""
        result_error = pytest.importorskip("claude_agent_sdk").ResultError
        return result_error(
            "Claude Code returned an error result: error_during_execution",
            data={
                "subtype": "error_during_execution",
                "errors": ["Connection closed mid-response"],
                "result": "API Error: 529 overloaded_error",
                "api_error_status": 529,
                "terminal_reason": "api_error",
            },
            exit_code=1,
        )

    def test_str_names_only_the_subtype(self):
        """Test the assumption the module is built on: str() says nothing useful."""
        error = self._build()
        assert str(error) == TERMINAL_MESSAGE
        assert "529" not in str(error)

    def test_fields_are_extracted_from_the_real_class(self):
        """Test result_error_fields reads the SDK's own attributes."""
        fields = result_error_fields(self._build())
        assert fields["api_error_status"] == 529
        assert fields["subtype"] == "error_during_execution"
        assert fields["terminal_reason"] == "api_error"
        assert fields["result"] == "API Error: 529 overloaded_error"
        assert fields["errors"] == ["Connection closed mid-response"]

    def test_classifies_as_a_retryable_server_error(self):
        """Test a real overloaded-API ResultError is retried, not fatal."""
        error = self._build()
        classified = classify_api_error(error)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 529
        assert isinstance(classified, TRANSIENT_ERRORS)
        assert classified.original_error is error

    def test_real_result_error_without_status_uses_payload_prose(self):
        """Test a real ResultError with no status classifies off errors prose."""
        result_error = pytest.importorskip("claude_agent_sdk").ResultError
        error = result_error(
            "Claude Code returned an error result: error_during_execution",
            data={
                "subtype": "error_during_execution",
                "errors": ["Connection closed mid-response"],
            },
            exit_code=1,
        )
        assert isinstance(classify_api_error(error), APIConnectionError)


# =============================================================================
# Text Path Tests
# =============================================================================


class TestTextClassification:
    """Tests for classification from the message text alone."""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("API rate limit exceeded", APIRateLimitError),
            ("Rate limit: too many requests", APIRateLimitError),
            ("HTTP 401 Unauthorized", APIAuthenticationError),
            ("HTTP 403 Forbidden", APIAuthenticationError),
            ("Unauthorized access to API", APIAuthenticationError),
            ("Invalid API key provided", APIAuthenticationError),
            ("Request timeout after 30 seconds", APITimeoutError),
            ("Request timed out", APITimeoutError),
            ("Connection refused", APIConnectionError),
            ("Network unreachable", APIConnectionError),
            ("Connection failed to server", APIConnectionError),
            ("Output blocked by content filtering policy", ContentFilterError),
            ("model claude-nope not_found", ModelUnavailableError),
            ("The model does not exist", ModelUnavailableError),
        ],
    )
    def test_message_maps_to_type(self, message, expected):
        """Test today's text rules keep classifying as they always did."""
        assert isinstance(classify_api_error(Exception(message)), expected)

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_server_status_in_text(self, status):
        """Test a standalone 5xx in the message yields the right status_code."""
        classified = classify_api_error(Exception(f"HTTP {status} Something Failed"))
        assert isinstance(classified, APIServerError)
        assert classified.status_code == status

    def test_case_insensitive(self):
        """Test the rules ignore case, as the old classifier did."""
        for message in ("rate limit exceeded", "RATE LIMIT EXCEEDED", "Rate Limit Exceeded"):
            assert isinstance(classify_api_error(Exception(message)), APIRateLimitError)

    def test_unmatched_message_is_plain_query_execution_error(self):
        """Test an unrecognised message stays unclassified rather than guessed."""
        error = Exception("Some unknown error")
        classified = classify_api_error(error)
        assert type(classified) is QueryExecutionError
        assert classified.original_error is error

    def test_empty_message_is_plain_query_execution_error(self):
        """Test an empty message matches nothing."""
        assert type(classify_api_error(Exception(""))) is QueryExecutionError

    def test_timeout_error_type_classifies_by_its_type_name(self):
        """Test a TimeoutError is a timeout even with an unhelpful message."""
        classified = classify_api_error(TimeoutError("boom"))
        assert isinstance(classified, APITimeoutError)


# =============================================================================
# Rule Ordering Tests
# =============================================================================


class TestRuleOrdering:
    """Tests that one rule's keywords do not get stolen by another's."""

    def test_service_unavailable_is_not_a_model_problem(self):
        """Test "503 Service Unavailable" is a server error, not a bad model id.

        The model rule requires "model" AND a not-found keyword; matching
        "unavailable" alone would send a transient 503 down the fallback chain.
        """
        classified = classify_api_error(Exception("HTTP 503 Service Unavailable"))
        assert not isinstance(classified, ModelUnavailableError)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 503

    def test_network_unreachable_is_not_a_model_problem(self):
        """Test "Network unreachable" is a connection error, not a bad model id."""
        classified = classify_api_error(Exception("Network unreachable"))
        assert not isinstance(classified, ModelUnavailableError)
        assert isinstance(classified, APIConnectionError)

    def test_content_filter_wins_over_a_status_in_the_same_message(self):
        """Test a filtered response is not read as a plain HTTP failure."""
        message = "API Error: 400 content filtering blocked the response"
        assert isinstance(classify_api_error(Exception(message)), ContentFilterError)


# =============================================================================
# Regression Tests
# =============================================================================


class TestLooseSubstringRegressions:
    """The two misclassifications this module exists to prevent."""

    def test_latency_figure_is_not_a_server_error(self):
        """Regression: `"500" in text` matched "request took 1500ms".

        A latency figure inside a larger number turned an ordinary message into
        a retryable APIServerError. The status rule is anchored on digit
        boundaries now, so 1500 is not 500.
        """
        classified = classify_api_error(Exception("request took 1500ms"))
        assert not isinstance(classified, APIServerError)
        assert type(classified) is QueryExecutionError

    def test_larger_numbers_containing_a_5xx_are_not_server_errors(self):
        """Regression, generalised: only a standalone 5xx counts as a status."""
        for message in ("elapsed 1500ms", "wrote 5031 bytes", "offset 25036"):
            assert not isinstance(classify_api_error(Exception(message)), APIServerError)

    def test_co_authored_by_trailer_is_not_an_auth_failure(self):
        """Regression: `"auth" in text` matched "Co-Authored-By".

        Every commit message this project writes carries that trailer, so any
        error echoing a git command became a NON-retryable
        APIAuthenticationError and ended the unattended run. Auth phrasings are
        whole words now.
        """
        message = (
            "Command failed: git commit -m 'fix: thing\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>'"
        )
        classified = classify_api_error(Exception(message))
        assert not isinstance(classified, APIAuthenticationError)

    def test_co_authored_by_in_result_payload_is_not_an_auth_failure(self):
        """Regression: the same trailer arriving via the structured payload."""
        error = FakeResultError(
            TERMINAL_MESSAGE,
            errors=["git commit failed\nCo-Authored-By: Claude <noreply@anthropic.com>"],
        )
        assert not isinstance(classify_api_error(error), APIAuthenticationError)

    def test_author_and_authorize_words_are_not_auth_failures(self):
        """Regression, generalised: "auth" inside a longer word never matches."""
        for message in ("Author: sebi", "authoring the changelog entry"):
            assert not isinstance(classify_api_error(Exception(message)), APIAuthenticationError)


# =============================================================================
# Importability Tests
# =============================================================================


class TestImportableWithoutSDK:
    """The module must classify errors with claude_agent_sdk absent.

    Some of the errors it classifies describe exactly that situation, so it
    duck-types the payload instead of importing the SDK.
    """

    def test_classification_works_with_sdk_patched_out(self):
        """Test import and classification with claude_agent_sdk unimportable."""
        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            reloaded = importlib.reload(agent_error_classify)
            try:
                error = FakeResultError(TERMINAL_MESSAGE, api_error_status=529)
                classified = reloaded.classify_api_error(error)
                assert isinstance(classified, APIServerError)
                assert classified.status_code == 529
                assert isinstance(
                    reloaded.classify_api_error(Exception("Connection refused")),
                    APIConnectionError,
                )
            finally:
                importlib.reload(agent_error_classify)

    def test_module_does_not_import_the_sdk(self):
        """Test the SDK is not imported - the payload is read with getattr."""
        assert "claude_agent_sdk" not in vars(agent_error_classify)
        source = inspect.getsource(agent_error_classify)
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        assert "import claude_agent_sdk" not in code
        assert "from claude_agent_sdk" not in code


class TestBareStatusNumbersInPayloadProse:
    """A bare 401/403 in echoed output must not end an unattended run.

    Folding ``result``/``errors`` into the searched text is what lets a real
    failure be recognised — and it also drags tool and command output in with
    it. A false ``APIServerError`` is merely retried; a false
    ``APIAuthenticationError`` is not retryable and kills the run, so auth
    status matching requires a status-like word nearby and 5xx does not.
    """

    @pytest.mark.parametrize(
        "message",
        [
            "wrote 403 bytes to disk",
            "process exited 401",
            "read 401 lines from the log",
            "offset 403 in the buffer",
        ],
    )
    def test_bare_number_is_not_an_auth_error(self, message: str) -> None:
        assert not isinstance(classify_api_error(Exception(message)), APIAuthenticationError)

    @pytest.mark.parametrize(
        "message",
        [
            "HTTP 401 Unauthorized",
            "HTTP 403 Forbidden",
            "status: 403",
            "error 401 returned by the API",
            "response code 403",
        ],
    )
    def test_status_with_context_is_still_an_auth_error(self, message: str) -> None:
        assert isinstance(classify_api_error(Exception(message)), APIAuthenticationError)

    def test_bare_number_inside_result_payload_prose(self) -> None:
        """The realistic shape: the number arrives via `errors`, not `str(e)`."""
        err = Exception("Claude Code returned an error result: error_during_execution")
        err.errors = ["Command output: wrote 403 bytes"]  # type: ignore[attr-defined]
        assert not isinstance(classify_api_error(err), APIAuthenticationError)

    def test_forbidden_word_alone_is_an_auth_error(self) -> None:
        """`403 Forbidden` must survive even without the digits."""
        assert isinstance(
            classify_api_error(Exception("Forbidden: you lack access")),
            APIAuthenticationError,
        )
